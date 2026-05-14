"""
app/admin/routes.py
===================
Halaman & API untuk role admin.

Fitur (sesuai spesifikasi):
- Approval pendaftaran mahasiswa & dosen.
- CRUD users (mahasiswa, dosen, admin) + reset password + nonaktifkan + ganti role.
- CRUD master mata kuliah (kode, nama, sks, rumpun, prasyarat, silabus).
- Plotting dosen ke kelas paralel + monitoring beban kerja.
- KRS distribusi: bulk enrollment, set kuota, filter syarat.
- Penjadwalan ruang dengan conflict detector.
- Gatekeeping: buka/tutup periode KRS dan input nilai.
- Audit log perubahan.
- Pembayaran: buat tagihan, verifikasi bukti.
- Nilai: lihat nilai semua mahasiswa per prodi.
- Organisasi: input keaktifan organisasi mahasiswa.
- Statistik real-time: total mahasiswa/dosen, login per prodi.
- Reset poin per semester.
"""
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    jsonify, current_app,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (
    User, ProgramStudi, ProfilMahasiswa, ProfilDosen,
    MataKuliah, Kelas, Jadwal, KRS, Tugas, JawabanTugas,
    Absen, Nilai, Poin, KonselingThread, KonselingPesan,
    Pembayaran, Notifikasi, AuditLog, LoginActivity,
    SystemSetting, dosen_prodi, Portfolio, Materi,
    SkpiPengajuan,
)
from app.utils import save_upload
from app.utils import record_audit

bp = Blueprint("admin", __name__)


@bp.before_request
@login_required
def _require_admin():
    if current_user.role not in ("admin", "superadmin") or current_user.status != "aktif":
        abort(403)


# Aksi super admin TIDAK dicatat (lihat app/utils/audit.py). Admin biasa
# tetap tercatat di AuditLog lewat helper satu pintu di bawah ini.
def _audit(aksi: str, target: str = None, detail: str = None):
    record_audit(aksi, target=target, detail=detail)


def _sanitize_role_for_admin(requested_role: str, fallback: str = "mahasiswa") -> str:
    """Hanya superadmin yang boleh menetapkan role ``superadmin``.

    Admin biasa yang mencoba membuat/mengedit user dengan role ``superadmin``
    akan otomatis dipaksa kembali ke ``fallback`` (biasanya role lama atau
    ``mahasiswa``). Hal ini mencegah eskalasi privilege oleh admin biasa.
    """
    if requested_role == "superadmin" and current_user.role != "superadmin":
        return fallback
    return requested_role


# =====================================================================
# DASHBOARD + STATISTIK REAL-TIME
# =====================================================================
@bp.route("/")
@bp.route("/dashboard")
def dashboard():
    total_mhs = User.query.filter_by(role="mahasiswa", status="aktif").count()
    total_dosen = User.query.filter_by(role="dosen", status="aktif").count()
    total_pending = User.query.filter_by(status="pending").count()
    total_prodi = ProgramStudi.query.count()
    total_matkul = MataKuliah.query.count()
    total_kelas = Kelas.query.count()

    # Statistik per prodi
    stats_prodi = []
    for p in ProgramStudi.query.all():
        jumlah_mhs = (
            db.session.query(ProfilMahasiswa)
            .filter_by(prodi_id=p.id)
            .count()
        )
        login_count = (
            db.session.query(LoginActivity)
            .filter(
                LoginActivity.prodi_id == p.id,
                LoginActivity.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0),
            ).count()
        )
        stats_prodi.append({"prodi": p, "mahasiswa": jumlah_mhs, "login_hari_ini": login_count})

    # Aktivitas login terbaru
    recent_logins = (
        LoginActivity.query.order_by(LoginActivity.created_at.desc()).limit(10).all()
    )

    return render_template(
        "admin/dashboard.html",
        total_mhs=total_mhs, total_dosen=total_dosen,
        total_pending=total_pending, total_prodi=total_prodi,
        total_matkul=total_matkul, total_kelas=total_kelas,
        stats_prodi=stats_prodi, recent_logins=recent_logins,
    )


# =====================================================================
# APPROVAL PENDAFTARAN
# =====================================================================
@bp.route("/approval")
def approval():
    pending = User.query.filter_by(status="pending").order_by(User.created_at.desc()).all()
    return render_template("admin/approval.html", pending=pending)


@bp.route("/approval/<int:uid>/<aksi>")
def approval_aksi(uid, aksi):
    u = User.query.get_or_404(uid)
    if aksi == "approve":
        u.status = "aktif"
        _audit("approve_user", str(u.id), u.email)
        flash(f"{u.email} disetujui.", "success")
    elif aksi == "reject":
        u.status = "ditolak"
        _audit("reject_user", str(u.id), u.email)
        flash(f"{u.email} ditolak.", "warning")
    db.session.commit()
    return redirect(url_for("admin.approval"))


# =====================================================================
# CRUD USERS
# =====================================================================
@bp.route("/users")
def users():
    role = request.args.get("role", "")
    q = User.query
    if role:
        q = q.filter_by(role=role)
    users = q.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users, selected_role=role)


@bp.route("/users/baru", methods=["GET", "POST"])
def user_baru():
    prodi_list = ProgramStudi.query.all()
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "") or "password123"
        role = request.form.get("role", "mahasiswa")
        if User.query.filter_by(email=email).first():
            flash("Email sudah ada.", "danger")
            return redirect(url_for("admin.user_baru"))

        # Admin biasa TIDAK boleh membuat akun super admin.
        role = _sanitize_role_for_admin(role, fallback="mahasiswa")
        if request.form.get("role") == "superadmin" and current_user.role != "superadmin":
            flash("Anda tidak berwenang membuat akun Super Admin.", "danger")
            return redirect(url_for("admin.user_baru"))

        u = User(nama=nama, email=email, role=role, status="aktif",
                 email_verified=True)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()

        if role == "mahasiswa":
            jk = request.form.get("jenis_kelas", "reguler")
            if jk not in ("reguler", "nonreguler"):
                jk = "reguler"
            db.session.add(ProfilMahasiswa(
                user_id=u.id,
                nim=request.form.get("nim", f"NIM{u.id}"),
                prodi_id=request.form.get("prodi_id", type=int) or prodi_list[0].id,
                angkatan=datetime.utcnow().year, semester=1,
                jenis_kelas=jk,
            ))
        elif role == "dosen":
            prof = ProfilDosen(user_id=u.id, nidn=request.form.get("nidn", f"NIDN{u.id}"))
            ids = request.form.getlist("prodi_ids", type=int)
            if ids:
                prof.prodi_list = ProgramStudi.query.filter(
                    ProgramStudi.id.in_(ids[:10])
                ).all()
            db.session.add(prof)
        db.session.commit()
        _audit("create_user", str(u.id), u.email)
        db.session.commit()
        flash("User dibuat.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/users.html", user=None, prodi_list=prodi_list, show_form=True, users=[], selected_role="")


@bp.route("/users/<int:uid>/edit", methods=["GET", "POST"])
def user_edit(uid):
    u = User.query.get_or_404(uid)
    prodi_list = ProgramStudi.query.all()

    # Admin biasa TIDAK boleh mengedit akun Super Admin sama sekali.
    if u.role == "superadmin" and current_user.role != "superadmin":
        flash("Anda tidak berwenang mengedit akun Super Admin.", "danger")
        return redirect(url_for("admin.users"))

    if request.method == "POST":
        u.nama = request.form.get("nama", u.nama).strip()
        u.email = request.form.get("email", u.email).strip().lower()
        # Admin biasa tidak boleh mempromosikan user menjadi Super Admin.
        new_role = request.form.get("role", u.role)
        if new_role == "superadmin" and current_user.role != "superadmin":
            flash("Anda tidak berwenang menetapkan role Super Admin.", "danger")
            new_role = u.role
        u.role = new_role
        u.status = request.form.get("status", u.status)
        u.no_telp = request.form.get("no_telp", "").strip()
        u.alamat = request.form.get("alamat", "").strip()
        new_pw = request.form.get("password", "").strip()
        if new_pw:
            u.set_password(new_pw)

        # Profil mahasiswa / dosen
        if u.role == "mahasiswa":
            pm = u.profil_mahasiswa or ProfilMahasiswa(user_id=u.id, nim=f"NIM{u.id}")
            pm.nim = request.form.get("nim", pm.nim)
            pm.prodi_id = request.form.get("prodi_id", type=int) or pm.prodi_id
            pm.semester = request.form.get("semester", type=int) or pm.semester
            pm.angkatan = request.form.get("angkatan", type=int) or pm.angkatan
            jk = request.form.get("jenis_kelas", pm.jenis_kelas or "reguler")
            pm.jenis_kelas = jk if jk in ("reguler", "nonreguler") else "reguler"
            if not u.profil_mahasiswa:
                db.session.add(pm)
        elif u.role == "dosen":
            pd = u.profil_dosen or ProfilDosen(user_id=u.id, nidn=f"NIDN{u.id}")
            pd.nidn = request.form.get("nidn", pd.nidn)
            pd.jabatan = request.form.get("jabatan", "").strip()
            ids = request.form.getlist("prodi_ids", type=int)
            if ids:
                pd.prodi_list = ProgramStudi.query.filter(
                    ProgramStudi.id.in_(ids[:10])
                ).all()
            if not u.profil_dosen:
                db.session.add(pd)

        _audit("edit_user", str(u.id), u.email)
        db.session.commit()
        flash("User diperbarui.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/users.html", user=u, prodi_list=prodi_list, show_form=True, users=[], selected_role="")


@bp.route("/users/<int:uid>/toggle")
def user_toggle(uid):
    u = User.query.get_or_404(uid)
    u.status = "nonaktif" if u.status == "aktif" else "aktif"
    _audit("toggle_user", str(u.id), u.status)
    db.session.commit()
    flash(f"Status {u.email} -> {u.status}.", "info")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
def user_delete(uid):
    u = User.query.get_or_404(uid)
    if u.role == "superadmin":
        flash("Tidak bisa hapus superadmin.", "danger")
        return redirect(url_for("admin.users"))
    _audit("delete_user", str(u.id), u.email)
    db.session.delete(u)
    db.session.commit()
    flash("User dihapus.", "success")
    return redirect(url_for("admin.users"))


# =====================================================================
# PRODI
# =====================================================================
@bp.route("/prodi", methods=["GET", "POST"])
def prodi():
    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        fak = request.form.get("fakultas", "").strip()
        if nama and fak and not ProgramStudi.query.filter_by(nama=nama).first():
            db.session.add(ProgramStudi(nama=nama, fakultas=fak))
            db.session.commit()
            _audit("create_prodi", nama)
            db.session.commit()
            flash("Prodi ditambahkan.", "success")
        return redirect(url_for("admin.prodi"))
    prodi_list = ProgramStudi.query.all()
    return render_template("admin/prodi.html", prodi_list=prodi_list)


# =====================================================================
# MASTER MATA KULIAH
# =====================================================================
@bp.route("/matkul")
def matkul():
    matkul_list = MataKuliah.query.order_by(MataKuliah.kode).all()
    return render_template("admin/matkul.html", matkul_list=matkul_list)


@bp.route("/matkul/baru", methods=["GET", "POST"])
@bp.route("/matkul/<int:mid>/edit", methods=["GET", "POST"])
def matkul_form(mid=None):
    mk = MataKuliah.query.get(mid) if mid else None
    prodi_list = ProgramStudi.query.all()
    matkul_all = MataKuliah.query.all()
    if request.method == "POST":
        kode = request.form.get("kode", "").strip()
        nama = request.form.get("nama", "").strip()
        sks = request.form.get("sks", type=int) or 3
        rumpun = request.form.get("rumpun", "").strip()
        jenis = request.form.get("jenis", "wajib")
        prasyarat_id = request.form.get("prasyarat_id", type=int) or None
        prodi_id = request.form.get("prodi_id", type=int)
        semester = request.form.get("semester", type=int) or 1
        f = request.files.get("silabus")
        path = save_upload(f, "silabus") if f else None

        if mk is None:
            mk = MataKuliah(prodi_id=prodi_id)
            db.session.add(mk)
        mk.kode = kode
        mk.nama = nama
        mk.sks = sks
        mk.rumpun = rumpun
        mk.jenis = jenis
        mk.prasyarat_id = prasyarat_id
        mk.prodi_id = prodi_id
        mk.semester = semester
        if path:
            mk.silabus = path
        _audit("save_matkul", kode)
        db.session.commit()
        flash("Mata kuliah disimpan.", "success")
        return redirect(url_for("admin.matkul"))
    return render_template("admin/matkul.html", mk=mk, prodi_list=prodi_list, matkul_all=matkul_all, show_form=True, matkul_list=[])


@bp.route("/matkul/<int:mid>/delete", methods=["POST"])
def matkul_delete(mid):
    mk = MataKuliah.query.get_or_404(mid)
    _audit("delete_matkul", mk.kode)
    db.session.delete(mk)
    db.session.commit()
    flash("Mata kuliah dihapus.", "success")
    return redirect(url_for("admin.matkul"))


# =====================================================================
# KELAS PARALEL + PLOTTING DOSEN + JADWAL + CONFLICT DETECTOR
# =====================================================================
@bp.route("/kelas")
def kelas():
    jk_filter = request.args.get("jenis_kelas", "")
    q = Kelas.query
    if jk_filter in ("reguler", "nonreguler"):
        q = q.filter_by(jenis_kelas=jk_filter)
    kelas_list = q.all()
    # beban kerja dosen (total SKS)
    beban = {}
    for k in kelas_list:
        beban[k.dosen_id] = beban.get(k.dosen_id, 0) + (k.matkul.sks if k.matkul else 0)
    dosen_list = User.query.filter_by(role="dosen", status="aktif").all()
    beban_rows = [(d, beban.get(d.id, 0)) for d in dosen_list]
    return render_template("admin/kelas.html", kelas_list=kelas_list, beban_rows=beban_rows, jk_filter=jk_filter)


@bp.route("/kelas/baru", methods=["GET", "POST"])
@bp.route("/kelas/<int:kid>/edit", methods=["GET", "POST"])
def kelas_form(kid=None):
    k = Kelas.query.get(kid) if kid else None
    matkul_list = MataKuliah.query.all()
    dosen_list = User.query.filter_by(role="dosen", status="aktif").all()
    if request.method == "POST":
        matkul_id = request.form.get("matkul_id", type=int)
        dosen_id = request.form.get("dosen_id", type=int)
        kode = request.form.get("kode_kelas", "A").strip().upper()
        kuota = request.form.get("kuota", type=int) or 40
        sem = request.form.get("semester_aktif", type=int) or 1
        ta = request.form.get("tahun_ajaran", "2024/2025-Ganjil").strip()
        jk = request.form.get("jenis_kelas", "reguler")
        if jk not in ("reguler", "nonreguler"):
            jk = "reguler"
        if not k:
            k = Kelas(matkul_id=matkul_id, dosen_id=dosen_id)
            db.session.add(k)
        k.matkul_id = matkul_id
        k.dosen_id = dosen_id
        k.kode_kelas = kode
        k.kuota = kuota
        k.semester_aktif = sem
        k.tahun_ajaran = ta
        k.jenis_kelas = jk
        _audit("save_kelas", f"matkul={matkul_id} dosen={dosen_id} jenis={jk}")
        db.session.commit()
        flash("Kelas disimpan.", "success")
        return redirect(url_for("admin.kelas"))
    return render_template("admin/kelas.html", k=k, matkul_list=matkul_list, dosen_list=dosen_list, show_form=True, kelas_list=[], beban_rows=[], jk_filter="")


@bp.route("/kelas/<int:kid>/delete", methods=["POST"])
def kelas_delete(kid):
    k = Kelas.query.get_or_404(kid)
    _audit("delete_kelas", str(kid))
    db.session.delete(k)
    db.session.commit()
    flash("Kelas dihapus.", "success")
    return redirect(url_for("admin.kelas"))


# ---- Jadwal + conflict detector ----
@bp.route("/jadwal", methods=["GET", "POST"])
def jadwal():
    if request.method == "POST":
        kelas_id = request.form.get("kelas_id", type=int)
        hari = request.form.get("hari", "Senin")
        jm = request.form.get("jam_mulai", "08:00")
        js = request.form.get("jam_selesai", "10:00")
        ruangan = request.form.get("ruangan", "R-101").strip()

        # Conflict detector: dosen / ruangan bertabrakan?
        kelas = Kelas.query.get(kelas_id)
        konflik = None
        for j in Jadwal.query.filter_by(hari=hari).all():
            if not (js <= j.jam_mulai or jm >= j.jam_selesai):
                if j.ruangan == ruangan:
                    konflik = f"Ruangan {ruangan} bentrok dengan {j.kelas.label}"
                    break
                if j.kelas.dosen_id == kelas.dosen_id:
                    konflik = f"Dosen sudah mengajar di {j.kelas.label} pada slot ini"
                    break
        if konflik:
            flash(f"Konflik jadwal: {konflik}", "danger")
            return redirect(url_for("admin.jadwal"))

        db.session.add(Jadwal(
            kelas_id=kelas_id, hari=hari, jam_mulai=jm,
            jam_selesai=js, ruangan=ruangan,
        ))
        _audit("save_jadwal", str(kelas_id))
        db.session.commit()
        flash("Jadwal ditambahkan.", "success")
        return redirect(url_for("admin.jadwal"))

    kelas_list = Kelas.query.all()
    jadwal_list = Jadwal.query.all()
    hari_order = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    grouped = {h: [] for h in hari_order}
    for j in jadwal_list:
        grouped.setdefault(j.hari, []).append(j)
    for h in grouped:
        grouped[h].sort(key=lambda j: j.jam_mulai)
    return render_template(
        "admin/jadwal.html", kelas_list=kelas_list, grouped=grouped,
        hari_order=hari_order,
    )


@bp.route("/jadwal/<int:jid>/delete", methods=["POST"])
def jadwal_delete(jid):
    j = Jadwal.query.get_or_404(jid)
    db.session.delete(j)
    _audit("delete_jadwal", str(jid))
    db.session.commit()
    flash("Jadwal dihapus.", "success")
    return redirect(url_for("admin.jadwal"))


# =====================================================================
# KRS DISTRIBUSI (Bulk Enrollment)
# =====================================================================
@bp.route("/krs", methods=["GET", "POST"])
def krs():
    prodi_list = ProgramStudi.query.all()
    selected_prodi = request.values.get("prodi_id", type=int)
    selected_sem = request.values.get("semester", type=int) or 1
    jk_filter = request.values.get("jenis_kelas", "")

    kelas_list = []
    if selected_prodi:
        kq = (
            Kelas.query.join(MataKuliah)
            .filter(MataKuliah.prodi_id == selected_prodi,
                    MataKuliah.semester == selected_sem)
        )
        if jk_filter in ("reguler", "nonreguler"):
            kq = kq.filter(Kelas.jenis_kelas == jk_filter)
        kelas_list = kq.all()

    if request.method == "POST":
        kelas_ids = request.form.getlist("kelas_ids", type=int)
        mhs_q = (
            User.query.join(ProfilMahasiswa)
            .filter(ProfilMahasiswa.prodi_id == selected_prodi,
                    ProfilMahasiswa.semester == selected_sem,
                    User.status == "aktif")
        )
        if jk_filter in ("reguler", "nonreguler"):
            mhs_q = mhs_q.filter(ProfilMahasiswa.jenis_kelas == jk_filter)
        mhs_list = mhs_q.all()
        added = 0
        for m in mhs_list:
            for kid in kelas_ids:
                exist = KRS.query.filter_by(
                    mahasiswa_id=m.id, kelas_id=kid, status="aktif"
                ).first()
                if exist:
                    continue
                db.session.add(KRS(
                    mahasiswa_id=m.id, kelas_id=kid, semester=selected_sem,
                ))
                added += 1
        _audit("bulk_krs", f"prodi={selected_prodi} sem={selected_sem} jk={jk_filter}", str(added))
        db.session.commit()
        flash(f"Berhasil distribusi KRS ke {added} entry.", "success")
        return redirect(url_for(
            "admin.krs", prodi_id=selected_prodi, semester=selected_sem,
            jenis_kelas=jk_filter,
        ))

    return render_template(
        "admin/krs.html", prodi_list=prodi_list, kelas_list=kelas_list,
        selected_prodi=selected_prodi, selected_sem=selected_sem,
        jk_filter=jk_filter,
    )


# =====================================================================
# GATEKEEPING (buka/tutup KRS & Nilai)
# =====================================================================
@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        SystemSetting.set("krs_open", "1" if request.form.get("krs_open") else "0")
        SystemSetting.set("nilai_open", "1" if request.form.get("nilai_open") else "0")
        _audit("set_gatekeeping",
               f"krs={SystemSetting.get('krs_open')} nilai={SystemSetting.get('nilai_open')}")
        db.session.commit()
        flash("Pengaturan disimpan.", "success")
        return redirect(url_for("admin.settings"))
    return render_template(
        "admin/settings.html",
        krs_open=SystemSetting.get("krs_open", "0") == "1",
        nilai_open=SystemSetting.get("nilai_open", "0") == "1",
    )


# =====================================================================
# AUDIT LOG
# =====================================================================
@bp.route("/audit")
def audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("admin/settings.html", logs=logs, view="audit")


# =====================================================================
# PEMBAYARAN
# =====================================================================
@bp.route("/pembayaran", methods=["GET", "POST"])
def pembayaran():
    if request.method == "POST":
        prodi_id = request.form.get("prodi_id", type=int)
        sem = request.form.get("semester", type=int) or 1
        nominal = request.form.get("nominal", type=int) or 0
        judul = request.form.get("judul", "UKT").strip()
        jk = request.form.get("jenis_kelas", "")

        mhs_q = (
            User.query.join(ProfilMahasiswa)
            .filter(ProfilMahasiswa.prodi_id == prodi_id,
                    ProfilMahasiswa.semester == sem,
                    User.status == "aktif")
        )
        if jk in ("reguler", "nonreguler"):
            mhs_q = mhs_q.filter(ProfilMahasiswa.jenis_kelas == jk)
        mhs_list = mhs_q.all()
        for m in mhs_list:
            db.session.add(Pembayaran(
                mahasiswa_id=m.id, judul=judul, nominal=nominal, semester=sem,
            ))
        _audit("buat_tagihan", f"prodi={prodi_id} sem={sem} jk={jk}", str(len(mhs_list)))
        db.session.commit()
        flash(f"Tagihan dibuat untuk {len(mhs_list)} mahasiswa.", "success")
        return redirect(url_for("admin.pembayaran"))

    jk_filter = request.args.get("jenis_kelas", "")
    bayar_q = Pembayaran.query
    if jk_filter in ("reguler", "nonreguler"):
        bayar_q = (
            bayar_q.join(User, Pembayaran.mahasiswa_id == User.id)
            .join(ProfilMahasiswa, ProfilMahasiswa.user_id == User.id)
            .filter(ProfilMahasiswa.jenis_kelas == jk_filter)
        )
    bayar = bayar_q.order_by(Pembayaran.created_at.desc()).all()
    prodi_list = ProgramStudi.query.all()
    return render_template(
        "admin/pembayaran.html", bayar=bayar, prodi_list=prodi_list,
        jk_filter=jk_filter,
    )


@bp.route("/pembayaran/<int:bid>/<aksi>")
def pembayaran_aksi(bid, aksi):
    b = Pembayaran.query.get_or_404(bid)
    if aksi == "verifikasi":
        b.status = "lunas"
        b.paid_at = datetime.utcnow()
    elif aksi == "tolak":
        b.status = "ditolak"
    _audit("verif_pembayaran", str(bid), b.status)
    db.session.commit()
    flash(f"Pembayaran {bid} -> {b.status}.", "info")
    return redirect(url_for("admin.pembayaran"))


# =====================================================================
# NILAI (rekap + edit override input dosen)
# =====================================================================
@bp.route("/nilai")
def nilai():
    """Halaman rekap nilai dengan filter Prodi -> Semester -> Mata Kuliah -> Jenis Kelas."""
    prodi_list = ProgramStudi.query.all()
    selected = request.args.get("prodi_id", type=int)
    semester = request.args.get("semester", type=int)
    matkul_id = request.args.get("matkul_id", type=int)
    jk_filter = request.args.get("jenis_kelas", "")

    matkul_choices = []
    if selected:
        mq = MataKuliah.query.filter_by(prodi_id=selected)
        if semester:
            mq = mq.filter_by(semester=semester)
        matkul_choices = mq.order_by(MataKuliah.kode).all()

    rows = []
    if selected:
        q = (
            db.session.query(Nilai, User, MataKuliah)
            .join(User, Nilai.mahasiswa_id == User.id)
            .join(Kelas, Nilai.kelas_id == Kelas.id)
            .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
            .join(ProfilMahasiswa, ProfilMahasiswa.user_id == User.id)
            .filter(ProfilMahasiswa.prodi_id == selected)
        )
        if semester:
            q = q.filter(Nilai.semester == semester)
        if matkul_id:
            q = q.filter(MataKuliah.id == matkul_id)
        if jk_filter in ("reguler", "nonreguler"):
            q = q.filter(ProfilMahasiswa.jenis_kelas == jk_filter)
        rows = q.order_by(User.nama).all()

    return render_template(
        "admin/nilai.html", prodi_list=prodi_list, rows=rows,
        selected=selected, semester=semester, matkul_id=matkul_id,
        matkul_choices=matkul_choices, jk_filter=jk_filter,
    )


@bp.route("/nilai/<int:nid>/edit", methods=["GET", "POST"])
def nilai_edit(nid):
    """Admin bisa override nilai yang sudah di-input dosen. Semua perubahan
    dicatat ke audit log supaya dosen/superadmin bisa lihat history."""
    n = Nilai.query.get_or_404(nid)
    if request.method == "POST":
        snapshot_lama = {
            "kuis": n.nilai_kuis, "tugas": n.nilai_tugas,
            "uts": n.nilai_uts, "uas": n.nilai_uas,
            "keaktifan": n.nilai_keaktifan, "proyek": n.nilai_proyek,
            "akhir": n.nilai_akhir, "grade": n.grade,
        }
        for komp in ["kuis", "tugas", "uts", "uas", "keaktifan", "proyek"]:
            v = request.form.get(komp, type=float)
            setattr(n, f"nilai_{komp}", v if v is not None else 0)
        n.catatan = request.form.get("catatan", "").strip() or None
        n.hitung()
        snapshot_baru = {
            "kuis": n.nilai_kuis, "tugas": n.nilai_tugas,
            "uts": n.nilai_uts, "uas": n.nilai_uas,
            "keaktifan": n.nilai_keaktifan, "proyek": n.nilai_proyek,
            "akhir": n.nilai_akhir, "grade": n.grade,
        }
        _audit(
            "edit_nilai",
            target=f"nilai#{n.id}",
            detail=f"mhs={n.mahasiswa.email} kelas={n.kelas.label} "
                   f"lama={snapshot_lama} baru={snapshot_baru}",
        )
        db.session.commit()
        flash("Nilai berhasil di-override. Perubahan tercatat di audit log.", "success")
        return redirect(url_for(
            "admin.nilai",
            prodi_id=n.mahasiswa.profil_mahasiswa.prodi_id
            if n.mahasiswa.profil_mahasiswa else None,
        ))
    return render_template(
        "admin/nilai.html", n=n,
        bobot=current_app.config["BOBOT_NILAI"],
    )


# =====================================================================
# ORGANISASI (input keaktifan) — CRUD lengkap
# =====================================================================
@bp.route("/organisasi", methods=["GET", "POST"])
def organisasi():
    if request.method == "POST":
        mhs_id = request.form.get("mahasiswa_id", type=int)
        teks = request.form.get("organisasi", "").strip()
        pm = ProfilMahasiswa.query.filter_by(user_id=mhs_id).first()
        if pm:
            pm.organisasi = teks or None
            _audit("simpan_organisasi", target=f"mhs#{mhs_id}",
                   detail=f"len={len(teks)}")
            db.session.commit()
            flash("Data organisasi disimpan.", "success")
        return redirect(url_for("admin.organisasi"))

    mhs_q = User.query.filter_by(role="mahasiswa").order_by(User.nama)
    jk_filter = request.args.get("jenis_kelas", "")
    if jk_filter in ("reguler", "nonreguler"):
        mhs_q = mhs_q.join(ProfilMahasiswa).filter(ProfilMahasiswa.jenis_kelas == jk_filter)
    mhs_list = mhs_q.all()
    return render_template("admin/organisasi.html", mhs_list=mhs_list, jk_filter=jk_filter)


@bp.route("/organisasi/<int:mhs_id>/edit", methods=["GET", "POST"])
def organisasi_edit(mhs_id):
    pm = ProfilMahasiswa.query.filter_by(user_id=mhs_id).first_or_404()
    if request.method == "POST":
        teks = request.form.get("organisasi", "").strip()
        pm.organisasi = teks or None
        _audit("edit_organisasi", target=f"mhs#{mhs_id}",
               detail=f"len={len(teks)}")
        db.session.commit()
        flash("Data organisasi diperbarui.", "success")
        return redirect(url_for("admin.organisasi"))
    return render_template("admin/organisasi.html", pm=pm, show_form=True, mhs_list=[], jk_filter="")


@bp.route("/organisasi/<int:mhs_id>/delete", methods=["POST"])
def organisasi_delete(mhs_id):
    pm = ProfilMahasiswa.query.filter_by(user_id=mhs_id).first_or_404()
    pm.organisasi = None
    _audit("hapus_organisasi", target=f"mhs#{mhs_id}")
    db.session.commit()
    flash("Data organisasi dihapus.", "info")
    return redirect(url_for("admin.organisasi"))


# =====================================================================
# PORTFOLIO (prestasi/karya mahasiswa — admin Full CRUD)
# =====================================================================
@bp.route("/portfolio")
def portfolio():
    mhs_id = request.args.get("mahasiswa_id", type=int)
    if mhs_id:
        items = Portfolio.query.filter_by(mahasiswa_id=mhs_id).order_by(
            Portfolio.tahun.desc().nulls_last(), Portfolio.created_at.desc()
        ).all()
        mhs = User.query.get(mhs_id)
    else:
        items = Portfolio.query.order_by(
            Portfolio.created_at.desc()
        ).limit(100).all()
        mhs = None
    mhs_list = User.query.filter_by(role="mahasiswa").order_by(User.nama).all()
    return render_template(
        "admin/portfolio.html", items=items, mhs=mhs,
        mhs_list=mhs_list, selected_mhs=mhs_id,
    )


@bp.route("/portfolio/baru", methods=["GET", "POST"])
def portfolio_baru():
    mhs_list = User.query.filter_by(role="mahasiswa").order_by(User.nama).all()
    if request.method == "POST":
        mhs_id = request.form.get("mahasiswa_id", type=int)
        judul = request.form.get("judul", "").strip()
        kategori = request.form.get("kategori", "").strip()
        deskripsi = request.form.get("deskripsi", "").strip()
        tahun = request.form.get("tahun", type=int)
        f = request.files.get("bukti")
        path = save_upload(f, "portfolio") if f else None

        if not mhs_id or not judul:
            flash("Mahasiswa dan judul wajib diisi.", "danger")
            return redirect(url_for("admin.portfolio_baru"))

        db.session.add(Portfolio(
            mahasiswa_id=mhs_id, judul=judul, kategori=kategori or None,
            deskripsi=deskripsi or None, tahun=tahun,
            bukti_path=path,
        ))
        _audit("create_portfolio", target=f"mhs#{mhs_id}", detail=judul)
        db.session.commit()
        flash("Portfolio ditambahkan.", "success")
        return redirect(url_for("admin.portfolio", mahasiswa_id=mhs_id))
    return render_template("admin/portfolio.html", mhs_list=mhs_list, item=None, show_form=True, portfolio_list=[])


@bp.route("/portfolio/<int:pid>/edit", methods=["GET", "POST"])
def portfolio_edit(pid):
    item = Portfolio.query.get_or_404(pid)
    mhs_list = User.query.filter_by(role="mahasiswa").order_by(User.nama).all()
    if request.method == "POST":
        item.judul = request.form.get("judul", item.judul).strip()
        item.kategori = request.form.get("kategori", "").strip() or None
        item.deskripsi = request.form.get("deskripsi", "").strip() or None
        item.tahun = request.form.get("tahun", type=int)
        f = request.files.get("bukti")
        path = save_upload(f, "portfolio") if f else None
        if path:
            item.bukti_path = path
        _audit("edit_portfolio", target=f"portfolio#{pid}", detail=item.judul)
        db.session.commit()
        flash("Portfolio diperbarui.", "success")
        return redirect(url_for("admin.portfolio", mahasiswa_id=item.mahasiswa_id))
    return render_template("admin/portfolio.html", mhs_list=mhs_list, item=item, show_form=True, portfolio_list=[])


@bp.route("/portfolio/<int:pid>/delete", methods=["POST"])
def portfolio_delete(pid):
    item = Portfolio.query.get_or_404(pid)
    mhs_id = item.mahasiswa_id
    _audit("delete_portfolio", target=f"portfolio#{pid}", detail=item.judul)
    db.session.delete(item)
    db.session.commit()
    flash("Portfolio dihapus.", "success")
    return redirect(url_for("admin.portfolio", mahasiswa_id=mhs_id))


# =====================================================================
# LEADERBOARD TOP 10 MAHASISWA (per Prodi)
# =====================================================================
@bp.route("/leaderboard")
def leaderboard():
    prodi_list = ProgramStudi.query.all()
    selected_prodi = request.args.get("prodi_id", type=int)
    jk_filter = request.args.get("jenis_kelas", "")
    top10 = []
    if selected_prodi:
        mhs_q = (
            db.session.query(User, ProfilMahasiswa)
            .join(ProfilMahasiswa, ProfilMahasiswa.user_id == User.id)
            .filter(ProfilMahasiswa.prodi_id == selected_prodi, User.status == "aktif")
        )
        if jk_filter in ("reguler", "nonreguler"):
            mhs_q = mhs_q.filter(ProfilMahasiswa.jenis_kelas == jk_filter)
        mhs_query = mhs_q.all()
        mhs_data = []
        for u, pm in mhs_query:
            nilai_list = Nilai.query.filter_by(mahasiswa_id=u.id).all()
            if not nilai_list:
                continue
            grade_map = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "E": 0.0}
            total_bobot = 0
            total_sks = 0
            for n in nilai_list:
                sks = n.kelas.matkul.sks if n.kelas and n.kelas.matkul else 3
                bobot = grade_map.get(n.grade, 0)
                total_bobot += bobot * sks
                total_sks += sks
            ipk = round(total_bobot / total_sks, 2) if total_sks > 0 else 0
            pm.ipk = ipk
            portfolio_items = Portfolio.query.filter_by(mahasiswa_id=u.id).all()
            skpi_total = (
                db.session.query(db.func.coalesce(db.func.sum(SkpiPengajuan.poin), 0))
                .filter(SkpiPengajuan.mahasiswa_id == u.id,
                        SkpiPengajuan.status == "approved")
                .scalar() or 0
            )
            skor = ipk + 0.05 * float(skpi_total)
            mhs_data.append({
                "user": u,
                "profil": pm,
                "ipk": ipk,
                "total_sks": total_sks,
                "semester_count": len(set(n.semester for n in nilai_list)),
                "organisasi": pm.organisasi,
                "portfolio": portfolio_items,
                "skpi_total": int(skpi_total),
                "skor": round(skor, 3),
            })
        db.session.commit()
        mhs_data.sort(key=lambda x: x["skor"], reverse=True)
        top10 = mhs_data[:10]
    return render_template(
        "admin/leaderboard.html", prodi_list=prodi_list,
        top10=top10, selected_prodi=selected_prodi,
        jk_filter=jk_filter,
    )


# =====================================================================
# EXPORT NILAI (CSV) — admin boleh download nilai dengan filter
# Prodi -> Semester -> Mata Kuliah
# =====================================================================
@bp.route("/nilai/export.csv")
def nilai_export_csv():
    import csv as _csv
    import io as _io
    from flask import Response

    prodi_id = request.args.get("prodi_id", type=int)
    semester = request.args.get("semester", type=int)
    matkul_id = request.args.get("matkul_id", type=int)

    q = (
        db.session.query(Nilai)
        .join(User, Nilai.mahasiswa_id == User.id)
        .join(Kelas, Nilai.kelas_id == Kelas.id)
        .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
        .join(ProfilMahasiswa, ProfilMahasiswa.user_id == User.id)
    )
    if prodi_id:
        q = q.filter(ProfilMahasiswa.prodi_id == prodi_id)
    if semester:
        q = q.filter(Nilai.semester == semester)
    if matkul_id:
        q = q.filter(MataKuliah.id == matkul_id)
    nilai_list = q.order_by(User.nama).all()

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow([
        "NIM", "Nama", "Email", "Prodi", "Kode Matkul", "Mata Kuliah",
        "Kelas", "Semester", "Kuis", "Tugas", "UTS", "UAS",
        "Keaktifan", "Proyek", "Akhir", "Grade", "Catatan",
    ])
    for n in nilai_list:
        pm = n.mahasiswa.profil_mahasiswa
        w.writerow([
            pm.nim if pm else "",
            n.mahasiswa.nama,
            n.mahasiswa.email,
            pm.prodi.nama if pm and pm.prodi else "",
            n.kelas.matkul.kode if n.kelas and n.kelas.matkul else "",
            n.kelas.matkul.nama if n.kelas and n.kelas.matkul else "",
            n.kelas.label if n.kelas else "",
            n.semester or "",
            n.nilai_kuis, n.nilai_tugas, n.nilai_uts, n.nilai_uas,
            n.nilai_keaktifan, n.nilai_proyek, n.nilai_akhir, n.grade,
            n.catatan or "",
        ])
    _audit(
        "export_nilai_csv",
        detail=(
            f"rows={len(nilai_list)} prodi={prodi_id or 'semua'} "
            f"semester={semester or 'semua'} matkul={matkul_id or 'semua'}"
        ),
    )
    db.session.commit()
    data = buf.getvalue().encode("utf-8-sig")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return Response(
        data, mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="nilai-{ts}.csv"'},
    )


# =====================================================================
# REKAP ABSENSI (lihat + download CSV) — filter Prodi -> Semester -> Matkul
# =====================================================================
def _hitung_rekap_absensi(prodi_id: int | None, semester: int | None,
                         matkul_id: int | None):
    """Bangun list rekap absensi terstruktur untuk render & export.

    Setiap baris berisi mahasiswa, kelas, dan akumulasi status
    (hadir/izin/sakit/alpha) beserta total pertemuan.
    """
    if not prodi_id:
        return [], 0

    kelas_q = (
        db.session.query(Kelas)
        .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
        .filter(MataKuliah.prodi_id == prodi_id)
    )
    if semester:
        kelas_q = kelas_q.filter(
            db.or_(
                Kelas.semester_aktif == semester,
                MataKuliah.semester == semester,
            )
        )
    if matkul_id:
        kelas_q = kelas_q.filter(MataKuliah.id == matkul_id)
    kelas_list = kelas_q.all()

    rekap = []
    total_pertemuan_global = 0
    for k in kelas_list:
        absens = Absen.query.filter_by(kelas_id=k.id).all()
        if not absens:
            continue
        pertemuan_count = max((a.pertemuan_ke for a in absens), default=0)
        total_pertemuan_global = max(total_pertemuan_global, pertemuan_count)
        # group per mahasiswa
        per_mhs: dict[int, dict] = {}
        for a in absens:
            slot = per_mhs.setdefault(
                a.mahasiswa_id,
                {"hadir": 0, "izin": 0, "sakit": 0, "alpha": 0},
            )
            slot[a.status] = slot.get(a.status, 0) + 1
        for mhs_id, counts in per_mhs.items():
            mhs = User.query.get(mhs_id)
            if not mhs:
                continue
            total = sum(counts.values()) or 1
            persen = counts["hadir"] / total * 100
            rekap.append({
                "mhs": mhs,
                "kelas": k,
                "matkul": k.matkul,
                "pertemuan": pertemuan_count,
                **counts,
                "total": sum(counts.values()),
                "persen_hadir": round(persen, 2),
            })
    rekap.sort(key=lambda r: (r["matkul"].kode if r["matkul"] else "", r["mhs"].nama))
    return rekap, total_pertemuan_global


@bp.route("/absensi")
def absensi():
    prodi_list = ProgramStudi.query.all()
    selected = request.args.get("prodi_id", type=int)
    semester = request.args.get("semester", type=int)
    matkul_id = request.args.get("matkul_id", type=int)
    jk_filter = request.args.get("jenis_kelas", "")

    matkul_choices = []
    if selected:
        mq = MataKuliah.query.filter_by(prodi_id=selected)
        if semester:
            mq = mq.filter_by(semester=semester)
        matkul_choices = mq.order_by(MataKuliah.kode).all()

    rekap, pertemuan_count = _hitung_rekap_absensi(selected, semester, matkul_id)
    # Filter rekap by jenis_kelas
    if jk_filter in ("reguler", "nonreguler"):
        rekap = [r for r in rekap
                 if r["mhs"].profil_mahasiswa and r["mhs"].profil_mahasiswa.jenis_kelas == jk_filter]
    return render_template(
        "admin/absensi.html", prodi_list=prodi_list, matkul_choices=matkul_choices,
        rekap=rekap, pertemuan_count=pertemuan_count,
        selected=selected, semester=semester, matkul_id=matkul_id,
        jk_filter=jk_filter,
    )


@bp.route("/absensi/export.csv")
def absensi_export_csv():
    import csv as _csv
    import io as _io
    from flask import Response

    prodi_id = request.args.get("prodi_id", type=int)
    semester = request.args.get("semester", type=int)
    matkul_id = request.args.get("matkul_id", type=int)

    rekap, _ = _hitung_rekap_absensi(prodi_id, semester, matkul_id)

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow([
        "NIM", "Nama", "Prodi", "Kode Matkul", "Mata Kuliah", "Kelas",
        "Semester Matkul", "Total Pertemuan",
        "Hadir", "Izin", "Sakit", "Alpha", "Total Absen", "% Hadir",
    ])
    for r in rekap:
        pm = r["mhs"].profil_mahasiswa
        mk = r["matkul"]
        k = r["kelas"]
        w.writerow([
            pm.nim if pm else "",
            r["mhs"].nama,
            pm.prodi.nama if pm and pm.prodi else "",
            mk.kode if mk else "",
            mk.nama if mk else "",
            k.label if k else "",
            mk.semester if mk else "",
            r["pertemuan"],
            r["hadir"], r["izin"], r["sakit"], r["alpha"],
            r["total"], r["persen_hadir"],
        ])
    _audit(
        "export_absensi_csv",
        detail=(
            f"rows={len(rekap)} prodi={prodi_id or 'semua'} "
            f"semester={semester or 'semua'} matkul={matkul_id or 'semua'}"
        ),
    )
    db.session.commit()
    data = buf.getvalue().encode("utf-8-sig")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return Response(
        data, mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="absensi-{ts}.csv"'},
    )


# =====================================================================
# POIN DOSEN (rekap, ranking, reset per prodi, export CSV)
# =====================================================================
@bp.route("/poin-dosen")
def poin_dosen():
    """Halaman rekap poin dosen yang diberikan mahasiswa.

    Fitur:
    - Filter per prodi
    - Ranking dosen berdasarkan total poin
    - Reset poin per prodi / semester / semua
    - Download CSV
    """
    prodi_list = ProgramStudi.query.all()
    selected_prodi = request.args.get("prodi_id", type=int)

    # Bangun ranking dosen
    ranking = []
    all_poin = Poin.query.all()

    # Filter dosen berdasarkan prodi jika dipilih
    if selected_prodi:
        # Ambil dosen yang terdaftar di prodi ini
        dosen_prodi_ids = (
            db.session.query(dosen_prodi.c.dosen_id)
            .filter(dosen_prodi.c.prodi_id == selected_prodi)
            .all()
        )
        dosen_ids = {r[0] for r in dosen_prodi_ids}
        # Juga include dosen yang punya kelas di prodi ini
        kelas_dosen_ids = (
            db.session.query(Kelas.dosen_id)
            .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
            .filter(MataKuliah.prodi_id == selected_prodi)
            .distinct().all()
        )
        dosen_ids.update(r[0] for r in kelas_dosen_ids)
        poin_list = [p for p in all_poin if p.dosen_id in dosen_ids]
    else:
        poin_list = all_poin

    # Aggregate per dosen
    dosen_agg = {}
    for p in poin_list:
        slot = dosen_agg.setdefault(p.dosen_id, {
            "total_poin": 0, "jumlah_pemberi": 0, "catatan_list": [],
        })
        slot["total_poin"] += p.nilai_poin
        slot["jumlah_pemberi"] += 1
        if p.catatan:
            slot["catatan_list"].append(p.catatan)

    for dosen_id, agg in dosen_agg.items():
        dosen = User.query.get(dosen_id)
        if not dosen:
            continue
        ranking.append({
            "dosen": dosen,
            "total_poin": agg["total_poin"],
            "jumlah_pemberi": agg["jumlah_pemberi"],
            "rata_rata": round(agg["total_poin"] / agg["jumlah_pemberi"], 1)
                         if agg["jumlah_pemberi"] else 0,
            "catatan_list": agg["catatan_list"][:5],  # max 5 komentar
        })

    ranking.sort(key=lambda x: x["total_poin"], reverse=True)

    # Statistik global
    total_entries = len(poin_list)
    total_poin_all = sum(p.nilai_poin for p in poin_list)

    return render_template(
        "admin/poin_dosen.html",
        prodi_list=prodi_list,
        selected_prodi=selected_prodi,
        ranking=ranking,
        total_entries=total_entries,
        total_poin_all=total_poin_all,
    )


@bp.route("/poin-dosen/export.csv")
def poin_export_csv():
    """Download rekap poin dosen sebagai CSV."""
    import csv as _csv
    import io as _io
    from flask import Response

    selected_prodi = request.args.get("prodi_id", type=int)

    q = db.session.query(Poin)
    if selected_prodi:
        dosen_ids_q = (
            db.session.query(Kelas.dosen_id)
            .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
            .filter(MataKuliah.prodi_id == selected_prodi)
            .distinct()
        )
        dosen_ids = {r[0] for r in dosen_ids_q.all()}
        # Also include from dosen_prodi table
        dp_ids = (
            db.session.query(dosen_prodi.c.dosen_id)
            .filter(dosen_prodi.c.prodi_id == selected_prodi).all()
        )
        dosen_ids.update(r[0] for r in dp_ids)
        q = q.filter(Poin.dosen_id.in_(dosen_ids))

    poin_list = q.order_by(Poin.dosen_id, Poin.mahasiswa_id).all()

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow([
        "NIDN", "Dosen", "NIM Pemberi", "Mahasiswa Pemberi",
        "Poin", "Semester", "Tahun Ajaran", "Catatan", "Tanggal",
    ])
    for p in poin_list:
        pd = p.dosen.profil_dosen
        pm = p.mahasiswa.profil_mahasiswa
        w.writerow([
            pd.nidn if pd else "",
            p.dosen.nama,
            pm.nim if pm else "",
            p.mahasiswa.nama,
            p.nilai_poin,
            p.semester,
            p.tahun_ajaran,
            p.catatan or "",
            p.created_at.strftime("%Y-%m-%d %H:%M") if p.created_at else "",
        ])

    # Tambahkan summary di akhir CSV
    w.writerow([])
    w.writerow(["=== RANGKUMAN ==="])
    w.writerow(["Dosen", "Total Poin", "Jumlah Pemberi", "Rata-rata"])
    dosen_summary = {}
    for p in poin_list:
        slot = dosen_summary.setdefault(p.dosen_id, {
            "nama": p.dosen.nama, "total": 0, "count": 0,
        })
        slot["total"] += p.nilai_poin
        slot["count"] += 1
    for d in sorted(dosen_summary.values(), key=lambda x: x["total"], reverse=True):
        avg = round(d["total"] / d["count"], 1) if d["count"] else 0
        w.writerow([d["nama"], d["total"], d["count"], avg])

    _audit("export_poin_csv", detail=f"rows={len(poin_list)} prodi={selected_prodi or 'semua'}")
    db.session.commit()

    data = buf.getvalue().encode("utf-8-sig")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return Response(
        data, mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="poin-dosen-{ts}.csv"'},
    )


@bp.route("/poin/reset", methods=["POST"])
def poin_reset():
    """Reset poin — bisa per prodi, per semester, atau semua."""
    scope = request.form.get("scope", "semester")
    prodi_id = request.form.get("prodi_id", type=int)

    if scope == "all":
        deleted = Poin.query.delete()
        _audit("reset_poin_semua", detail=f"deleted={deleted}")
        db.session.commit()
        flash(f"Semua poin direset ({deleted} entri dihapus).", "success")
    elif scope == "prodi" and prodi_id:
        # Cari dosen yang mengajar di prodi ini
        dosen_ids_q = (
            db.session.query(Kelas.dosen_id)
            .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
            .filter(MataKuliah.prodi_id == prodi_id)
            .distinct()
        )
        dosen_ids = {r[0] for r in dosen_ids_q.all()}
        dp_ids = (
            db.session.query(dosen_prodi.c.dosen_id)
            .filter(dosen_prodi.c.prodi_id == prodi_id).all()
        )
        dosen_ids.update(r[0] for r in dp_ids)
        deleted = Poin.query.filter(Poin.dosen_id.in_(dosen_ids)).delete(
            synchronize_session="fetch"
        )
        prodi = ProgramStudi.query.get(prodi_id)
        _audit("reset_poin_prodi", target=prodi.nama if prodi else str(prodi_id),
               detail=str(deleted))
        db.session.commit()
        flash(f"Poin prodi {prodi.nama if prodi else prodi_id} direset ({deleted} entri).", "success")
    else:
        sem = request.form.get("semester", type=int) or 1
        deleted = Poin.query.filter_by(semester=sem).delete()
        _audit("reset_poin", target=f"sem={sem}", detail=str(deleted))
        db.session.commit()
        flash(f"Poin semester {sem} direset ({deleted} entri dihapus).", "success")
    return redirect(url_for("admin.poin_dosen"))


# =====================================================================
# API stats real-time (JSON) untuk chart di dashboard
# =====================================================================
@bp.route("/profile", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        current_user.nama = request.form.get("nama", current_user.nama).strip()
        current_user.no_telp = request.form.get("no_telp", "").strip() or None
        current_user.alamat = request.form.get("alamat", "").strip() or None
        f = request.files.get("foto")
        path = save_upload(f, "profile", allow_image_only=True) if f else None
        if path:
            current_user.foto = path
        new_pw = request.form.get("password", "").strip()
        if new_pw and len(new_pw) >= 6:
            current_user.set_password(new_pw)
        db.session.commit()
        flash("Profil diperbarui.", "success")
        return redirect(url_for("admin.profile"))
    return render_template("admin/profile.html")


@bp.route("/api/stats")
def stats_json():
    data = []
    for p in ProgramStudi.query.all():
        data.append({
            "prodi": p.nama,
            "mahasiswa": ProfilMahasiswa.query.filter_by(prodi_id=p.id).count(),
            "login": LoginActivity.query.filter_by(prodi_id=p.id).count(),
        })
    return jsonify(data)


# =====================================================================
# SKPI - Review pengajuan sertifikat SKPI dari mahasiswa
# =====================================================================
@bp.route("/skpi")
def skpi_list():
    """Daftar pengajuan SKPI. Default tampil pending dulu."""
    status_filter = request.args.get("status", "pending")
    q = SkpiPengajuan.query
    if status_filter in ("pending", "approved", "rejected"):
        q = q.filter_by(status=status_filter)
    pengajuan_list = q.order_by(SkpiPengajuan.created_at.desc()).all()

    counts = {
        "pending": SkpiPengajuan.query.filter_by(status="pending").count(),
        "approved": SkpiPengajuan.query.filter_by(status="approved").count(),
        "rejected": SkpiPengajuan.query.filter_by(status="rejected").count(),
    }
    counts["total"] = counts["pending"] + counts["approved"] + counts["rejected"]
    total_poin_disetujui = db.session.query(
        db.func.coalesce(db.func.sum(SkpiPengajuan.poin), 0)
    ).filter(SkpiPengajuan.status == "approved").scalar() or 0

    return render_template(
        "admin/skpi.html",
        pengajuan_list=pengajuan_list,
        status_filter=status_filter,
        counts=counts,
        total_poin_disetujui=total_poin_disetujui,
    )


@bp.route("/skpi/<int:sid>/decide", methods=["POST"])
def skpi_decide(sid):
    """Admin meng-approve (dengan poin 1..4) atau reject pengajuan SKPI."""
    p = SkpiPengajuan.query.get_or_404(sid)
    aksi = (request.form.get("aksi") or "").strip().lower()
    catatan = (request.form.get("catatan") or "").strip() or None

    if aksi == "approve":
        try:
            poin = int(request.form.get("poin", "0"))
        except ValueError:
            poin = 0
        if poin < 1 or poin > 4:
            flash("Poin SKPI harus antara 1 sampai 4.", "warning")
            return redirect(url_for("admin.skpi_list", status="pending"))
        p.status = "approved"
        p.poin = poin
        p.catatan_admin = catatan
        p.reviewed_by = current_user.id
        p.reviewed_at = datetime.utcnow()
        try:
            n = Notifikasi(
                user_id=p.mahasiswa_id,
                judul="Pengajuan SKPI disetujui",
                isi=f"Sertifikat '{p.judul}' disetujui dengan {poin} poin SKPI.",
            )
            db.session.add(n)
        except Exception:
            pass
        _audit("skpi_approve", str(p.id), f"poin={poin}; judul={p.judul}")
        flash(f"Pengajuan SKPI #{p.id} disetujui dengan {poin} poin.", "success")

    elif aksi == "reject":
        p.status = "rejected"
        p.poin = None
        p.catatan_admin = catatan or "Ditolak oleh admin."
        p.reviewed_by = current_user.id
        p.reviewed_at = datetime.utcnow()
        try:
            n = Notifikasi(
                user_id=p.mahasiswa_id,
                judul="Pengajuan SKPI ditolak",
                isi=(
                    f"Sertifikat '{p.judul}' ditolak."
                    + (f" Catatan: {p.catatan_admin}" if p.catatan_admin else "")
                ),
            )
            db.session.add(n)
        except Exception:
            pass
        _audit("skpi_reject", str(p.id), f"judul={p.judul}")
        flash(f"Pengajuan SKPI #{p.id} ditolak.", "warning")

    else:
        flash("Aksi tidak dikenali.", "warning")
        return redirect(url_for("admin.skpi_list", status="pending"))

    db.session.commit()
    return redirect(url_for("admin.skpi_list", status=request.form.get("redirect_status", "pending")))


