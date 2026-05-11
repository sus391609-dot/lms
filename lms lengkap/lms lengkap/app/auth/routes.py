"""
app/auth/routes.py
==================
Seluruh flow autentikasi: landing (1 form unified), register mahasiswa/dosen
(dengan verifikasi SMTP), lupa password, reset password, logout.

Perubahan utama:
- Landing sekarang 1 form (email + password) — role auto-detect dari DB.
- Statistik live (mahasiswa aktif, dosen aktif, jumlah prodi) ditampilkan
  di halaman login.
- Mahasiswa & dosen tidak lagi perlu memilih prodi saat login.
- Route legacy ``/login/<role>`` tetap ada dan redirect ke halaman utama
  (backward compat).
"""
from datetime import datetime, timedelta

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
)
from flask_login import login_user, logout_user, login_required, current_user

from app.extensions import db
from app.models import (
    User, ProgramStudi, ProfilMahasiswa, ProfilDosen,
    EmailVerification, LoginActivity,
)
from app.utils import generate_code, send_verification_code

bp = Blueprint("auth", __name__)


# =====================================================================
# LANDING + UNIFIED LOGIN
# =====================================================================
def _login_stats() -> dict:
    """Statistik live untuk dipajang di halaman login."""
    return {
        "mahasiswa_aktif": User.query.filter_by(role="mahasiswa", status="aktif").count(),
        "dosen_aktif": User.query.filter_by(role="dosen", status="aktif").count(),
        "prodi": ProgramStudi.query.count(),
    }


@bp.route("/", methods=["GET", "POST"])
@bp.route("/login", methods=["GET", "POST"])
def landing():
    if current_user.is_authenticated:
        return redirect(url_for(f"{current_user.role}.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Email atau password salah.", "danger")
            return render_template("auth/landing.html", stats=_login_stats())
        if user.status == "pending":
            flash("Akun Anda masih menunggu verifikasi admin.", "warning")
            return render_template("auth/landing.html", stats=_login_stats())
        if user.status == "nonaktif":
            flash("Akun Anda dinonaktifkan. Hubungi admin.", "danger")
            return render_template("auth/landing.html", stats=_login_stats())
        if user.status == "ditolak":
            flash("Pendaftaran Anda ditolak admin.", "danger")
            return render_template("auth/landing.html", stats=_login_stats())
        if not user.email_verified:
            session["pending_email"] = user.email
            flash("Email belum diverifikasi. Silakan verifikasi.", "warning")
            return redirect(url_for("auth.verify_email"))

        login_user(user)
        user.last_login = datetime.utcnow()
        prodi_id_for_log = (
            user.profil_mahasiswa.prodi_id if user.profil_mahasiswa else None
        )
        db.session.add(LoginActivity(
            user_id=user.id, role=user.role, prodi_id=prodi_id_for_log,
        ))
        db.session.commit()
        return redirect(url_for(f"{user.role}.dashboard"))

    return render_template("auth/landing.html", stats=_login_stats())


# Route legacy (/login/mahasiswa, dst.) redirect ke landing agar link lama
# tidak broken tapi semua user pakai 1 form.
@bp.route("/login/mahasiswa", methods=["GET", "POST"])
@bp.route("/login/dosen", methods=["GET", "POST"])
@bp.route("/login/admin", methods=["GET", "POST"])
@bp.route("/login/superadmin", methods=["GET", "POST"])
def login_legacy():
    return redirect(url_for("auth.landing"))


# Alias lama supaya ``url_for('auth.login_mahasiswa')`` dst. tetap jalan.
bp.add_url_rule(
    "/_legacy/login/mahasiswa", endpoint="login_mahasiswa",
    view_func=login_legacy, methods=["GET", "POST"],
)
bp.add_url_rule(
    "/_legacy/login/dosen", endpoint="login_dosen",
    view_func=login_legacy, methods=["GET", "POST"],
)
bp.add_url_rule(
    "/_legacy/login/admin", endpoint="login_admin",
    view_func=login_legacy, methods=["GET", "POST"],
)
bp.add_url_rule(
    "/_legacy/login/superadmin", endpoint="login_superadmin",
    view_func=login_legacy, methods=["GET", "POST"],
)


# =====================================================================
# REGISTER MAHASISWA
# =====================================================================
@bp.route("/register/mahasiswa", methods=["GET", "POST"])
def register_mahasiswa():
    prodi_list = ProgramStudi.query.all()
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        nim = request.form.get("nim", "").strip()
        prodi_id = request.form.get("prodi_id", type=int)
        no_telp = request.form.get("no_telp", "").strip()
        jenis_kelas = request.form.get("jenis_kelas", "reguler").strip()
        if jenis_kelas not in ("reguler", "nonreguler"):
            jenis_kelas = "reguler"

        if not all([nama, email, password, nim, prodi_id]):
            flash("Lengkapi semua field wajib.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list)
        if password != password2:
            flash("Konfirmasi password tidak cocok.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list)
        if len(password) < 6:
            flash("Password minimal 6 karakter.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list)
        if User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list)
        if ProfilMahasiswa.query.filter_by(nim=nim).first():
            flash("NIM sudah terdaftar.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list)

        user = User(
            nama=nama, email=email, role="mahasiswa",
            status="pending", email_verified=False, no_telp=no_telp,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        db.session.add(ProfilMahasiswa(
            user_id=user.id, nim=nim, prodi_id=prodi_id,
            angkatan=datetime.utcnow().year, semester=1,
            jenis_kelas=jenis_kelas,
        ))
        db.session.commit()

        _, sent_ok = _issue_code(email, "register")
        session["pending_email"] = email
        flash("Pendaftaran berhasil! Silakan lakukan verifikasi email.", "success")
        _flash_email_status(sent_ok, email)
        return redirect(url_for("auth.verify_email"))

    return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list)


# =====================================================================
# REGISTER DOSEN
# =====================================================================
@bp.route("/register/dosen", methods=["GET", "POST"])
def register_dosen():
    prodi_list = ProgramStudi.query.all()
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        nidn = request.form.get("nidn", "").strip()
        prodi_ids = request.form.getlist("prodi_ids", type=int)
        no_telp = request.form.get("no_telp", "").strip()

        if not all([nama, email, password, nidn, prodi_ids]):
            flash("Lengkapi semua field wajib termasuk minimal 1 prodi.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")
        if not email.endswith("@yarsipratama.ac.id"):
            flash("Email dosen harus berdomain @yarsipratama.ac.id.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")
        if password != password2:
            flash("Konfirmasi password tidak cocok.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")
        if len(prodi_ids) > 10:
            flash("Maksimal 10 prodi per dosen.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")
        if User.query.filter_by(email=email).first():
            flash("Email sudah terdaftar.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")
        if ProfilDosen.query.filter_by(nidn=nidn).first():
            flash("NIDN sudah terdaftar.", "danger")
            return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")

        user = User(
            nama=nama, email=email, role="dosen",
            status="pending", email_verified=False, no_telp=no_telp,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        prof = ProfilDosen(user_id=user.id, nidn=nidn)
        prof.prodi_list = ProgramStudi.query.filter(
            ProgramStudi.id.in_(prodi_ids)
        ).all()
        db.session.add(prof)
        db.session.commit()

        _, sent_ok = _issue_code(email, "register")
        session["pending_email"] = email
        flash("Pendaftaran berhasil! Silakan lakukan verifikasi email.", "success")
        _flash_email_status(sent_ok, email)
        return redirect(url_for("auth.verify_email"))

    return render_template("auth/register_mahasiswa.html", prodi_list=prodi_list, view="dosen")


# =====================================================================
# VERIFIKASI EMAIL
# =====================================================================
def _issue_code(email: str, purpose: str) -> tuple[str, bool]:
    """Buat kode verifikasi, simpan ke DB, coba kirim email.

    Return ``(code, sent_ok)``. Bila ``sent_ok`` False, pemanggil dapat
    memberi tahu user (flash + fallback alternatif).
    """
    code = generate_code()
    db.session.add(EmailVerification(
        email=email, code=code, purpose=purpose,
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    ))
    db.session.commit()
    sent_ok = send_verification_code(email, code, purpose)
    return code, sent_ok


def _flash_email_status(sent_ok: bool, email: str) -> None:
    if sent_ok:
        flash(f"Kode verifikasi dikirim ke {email}. Cek inbox/spam.", "success")
    else:
        flash(
            "Gagal mengirim email. Hubungi admin untuk mendapatkan kode verifikasi, "
            "atau coba lagi dalam beberapa menit.",
            "danger",
        )


@bp.route("/verify_email", methods=["GET", "POST"])
def verify_email():
    email = session.get("pending_email")
    if not email:
        flash("Tidak ada email pending verifikasi.", "warning")
        return redirect(url_for("auth.landing"))

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        ev = (
            EmailVerification.query.filter_by(
                email=email, code=code, used=False,
            )
            .order_by(EmailVerification.created_at.desc())
            .first()
        )
        if not ev or ev.expires_at < datetime.utcnow():
            flash("Kode verifikasi tidak valid atau kadaluarsa.", "danger")
            return render_template("auth/verify_email.html", email=email)
        ev.used = True
        user = User.query.filter_by(email=email).first()
        if user:
            user.email_verified = True
        db.session.commit()
        flash("Email terverifikasi. Akun menunggu approval admin.", "success")
        session.pop("pending_email", None)
        return redirect(url_for("auth.landing"))

    return render_template("auth/verify_email.html", email=email)


@bp.route("/verify_email/resend", methods=["POST"])
def verify_resend():
    email = session.get("pending_email")
    if email:
        _, sent_ok = _issue_code(email, "register")
        _flash_email_status(sent_ok, email)
    return redirect(url_for("auth.verify_email"))


# =====================================================================
# LUPA PASSWORD
# =====================================================================
@bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            _, sent_ok = _issue_code(email, "reset")
            session["reset_email"] = email
            _flash_email_status(sent_ok, email)
            return redirect(url_for("auth.reset_password"))
        flash("Email tidak terdaftar.", "danger")
    return render_template("auth/forgot_password.html")


@bp.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    email = session.get("reset_email")
    if not email:
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        code = request.form.get("code", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if password != password2 or len(password) < 6:
            flash("Password minimal 6 karakter & harus cocok.", "danger")
            return render_template("auth/forgot_password.html", email=email, view="reset")
        ev = (
            EmailVerification.query.filter_by(
                email=email, code=code, used=False, purpose="reset",
            )
            .order_by(EmailVerification.created_at.desc())
            .first()
        )
        if not ev or ev.expires_at < datetime.utcnow():
            flash("Kode tidak valid atau kadaluarsa.", "danger")
            return render_template("auth/forgot_password.html", email=email, view="reset")
        user = User.query.filter_by(email=email).first()
        user.set_password(password)
        ev.used = True
        db.session.commit()
        session.pop("reset_email", None)
        flash("Password diperbarui. Silakan login.", "success")
        return redirect(url_for("auth.landing"))
    return render_template("auth/forgot_password.html", email=email, view="reset")


# =====================================================================
# LOGOUT
# =====================================================================
@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Anda telah keluar.", "info")
    return redirect(url_for("auth.landing"))


