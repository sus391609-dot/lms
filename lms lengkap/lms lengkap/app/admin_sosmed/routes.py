"""
app/admin_sosmed/routes.py
==========================
Blueprint khusus Admin Sosmed / Konten Publik.

Role ``admin_sosmed`` hanya mengelola konten yang tampil di website publik:
- Berita kampus
- Kegiatan kampus
- Kerja sama / kemitraan
- Pendaftar PMB (view + ubah status)

Admin LMS reguler (``admin`` / ``superadmin``) tidak punya akses CMS ini
sehingga tanggung jawab CMS publik benar-benar terpisah dari operasional
akademik.
"""
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (
    Berita, Kegiatan, KerjaSama, PendaftaranPMB, ProgramStudi, AuditLog,
)
from app.utils import save_upload, record_audit

bp = Blueprint("admin_sosmed", __name__)


# ---------------------------------------------------------------------
# Access guard
# ---------------------------------------------------------------------
@bp.before_request
@login_required
def _require_sosmed():
    allowed = ("admin_sosmed", "admin", "superadmin")
    if current_user.role not in allowed or current_user.status != "aktif":
        abort(403)


def _audit(aksi: str, target: str | None = None, detail: str | None = None):
    record_audit(aksi, target=target, detail=detail)


def _parse_dt(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None


def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


# =====================================================================
# DASHBOARD
# =====================================================================
@bp.route("/")
@bp.route("/dashboard")
def dashboard():
    # Counter dasar
    total_berita = Berita.query.count()
    pub_berita = Berita.query.filter_by(status="published").count()
    draft_berita = Berita.query.filter_by(status="draft").count()
    total_kegiatan = Kegiatan.query.count()
    pub_kegiatan = Kegiatan.query.filter_by(status="published").count()
    total_kerjasama = KerjaSama.query.count()
    pub_kerjasama = KerjaSama.query.filter_by(status="published").count()
    total_pendaftar = PendaftaranPMB.query.count()
    pendaftar_baru = PendaftaranPMB.query.filter_by(status="baru").count()
    pendaftar_diproses = PendaftaranPMB.query.filter_by(status="diproses").count()
    pendaftar_diterima = PendaftaranPMB.query.filter_by(status="diterima").count()

    # Top viewed berita / kegiatan
    top_berita = (
        Berita.query.filter_by(status="published")
        .order_by(Berita.views.desc()).limit(5).all()
    )
    latest_berita = (
        Berita.query.order_by(Berita.created_at.desc()).limit(5).all()
    )
    latest_kegiatan = (
        Kegiatan.query.order_by(Kegiatan.created_at.desc()).limit(5).all()
    )
    latest_pendaftar = (
        PendaftaranPMB.query.order_by(PendaftaranPMB.created_at.desc()).limit(5).all()
    )

    # Sebaran kategori berita untuk chart
    kategori_berita = {}
    for row in db.session.query(Berita.kategori, db.func.count(Berita.id)).group_by(
        Berita.kategori
    ).all():
        kategori_berita[row[0] or "Umum"] = row[1]

    # Aktivitas terakhir admin sosmed (audit log filter aksi)
    audit_keys = (
        "save_berita", "delete_berita",
        "save_kegiatan", "delete_kegiatan",
        "save_kerjasama", "delete_kerjasama",
    )
    aktivitas = (
        AuditLog.query.filter(AuditLog.aksi.in_(audit_keys))
        .order_by(AuditLog.created_at.desc()).limit(10).all()
    )

    return render_template(
        "admin_sosmed/dashboard.html",
        total_berita=total_berita, pub_berita=pub_berita, draft_berita=draft_berita,
        total_kegiatan=total_kegiatan, pub_kegiatan=pub_kegiatan,
        total_kerjasama=total_kerjasama, pub_kerjasama=pub_kerjasama,
        total_pendaftar=total_pendaftar,
        pendaftar_baru=pendaftar_baru,
        pendaftar_diproses=pendaftar_diproses,
        pendaftar_diterima=pendaftar_diterima,
        top_berita=top_berita,
        latest_berita=latest_berita,
        latest_kegiatan=latest_kegiatan,
        latest_pendaftar=latest_pendaftar,
        kategori_berita=kategori_berita,
        aktivitas=aktivitas,
    )


# Alias supaya url_for('admin_sosmed.profile') tidak meledak (dipanggil
# topbar _dashboard_base.html lewat current_user.role + '.profile').
@bp.route("/profil")
def profile():
    return redirect(url_for("admin_sosmed.dashboard"))


# =====================================================================
# BERITA
# =====================================================================
@bp.route("/berita")
def berita_list():
    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    query = Berita.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Berita.judul.ilike(like), Berita.kategori.ilike(like)))
    total = query.count()
    rows = (
        query.order_by(Berita.published_at.desc())
        .limit(per_page).offset((page - 1) * per_page).all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "admin_sosmed/berita_list.html",
        rows=rows, q=q, page=page, pages=pages, total=total,
    )


@bp.route("/berita/baru", methods=["GET", "POST"])
@bp.route("/berita/<int:bid>/edit", methods=["GET", "POST"])
def berita_form(bid=None):
    b = Berita.query.get(bid) if bid else None
    if request.method == "POST":
        judul = request.form.get("judul", "").strip()
        if not judul:
            flash("Judul wajib diisi.", "danger")
            return render_template("admin_sosmed/berita_form.html", b=b)
        isi = request.form.get("isi", "").strip()
        if not isi:
            flash("Isi berita wajib diisi.", "danger")
            return render_template("admin_sosmed/berita_form.html", b=b)

        if b is None:
            b = Berita(judul=judul, isi=isi, penulis_id=current_user.id)
            db.session.add(b)
        b.judul = judul
        b.isi = isi
        b.ringkasan = request.form.get("ringkasan", "").strip() or None
        b.kategori = request.form.get("kategori", "Umum").strip() or "Umum"
        b.status = request.form.get("status", "published")
        pub = _parse_dt(request.form.get("published_at", ""))
        if pub:
            b.published_at = pub

        f = request.files.get("gambar")
        if f and f.filename:
            path = save_upload(f, "berita", allow_image_only=True)
            if path:
                b.gambar = path
            else:
                flash("Format gambar tidak didukung (gunakan PNG/JPG).", "warning")
        _audit("save_berita", judul[:80])
        db.session.commit()
        flash("Berita disimpan.", "success")
        return redirect(url_for("admin_sosmed.berita_list"))
    return render_template("admin_sosmed/berita_form.html", b=b)


@bp.route("/berita/<int:bid>/delete", methods=["POST"])
def berita_delete(bid):
    b = Berita.query.get_or_404(bid)
    _audit("delete_berita", b.judul[:80])
    db.session.delete(b)
    db.session.commit()
    flash("Berita dihapus.", "success")
    return redirect(url_for("admin_sosmed.berita_list"))


# =====================================================================
# KEGIATAN
# =====================================================================
@bp.route("/kegiatan")
def kegiatan_list():
    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    query = Kegiatan.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Kegiatan.judul.ilike(like), Kegiatan.lokasi.ilike(like)))
    total = query.count()
    rows = (
        query.order_by(Kegiatan.tanggal_mulai.desc().nullslast(), Kegiatan.created_at.desc())
        .limit(per_page).offset((page - 1) * per_page).all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "admin_sosmed/kegiatan_list.html",
        rows=rows, q=q, page=page, pages=pages, total=total,
    )


@bp.route("/kegiatan/baru", methods=["GET", "POST"])
@bp.route("/kegiatan/<int:kid>/edit", methods=["GET", "POST"])
def kegiatan_form(kid=None):
    k = Kegiatan.query.get(kid) if kid else None
    if request.method == "POST":
        judul = request.form.get("judul", "").strip()
        isi = request.form.get("isi", "").strip()
        if not judul or not isi:
            flash("Judul & isi wajib diisi.", "danger")
            return render_template("admin_sosmed/kegiatan_form.html", k=k)

        if k is None:
            k = Kegiatan(judul=judul, isi=isi, penulis_id=current_user.id)
            db.session.add(k)
        k.judul = judul
        k.isi = isi
        k.ringkasan = request.form.get("ringkasan", "").strip() or None
        k.lokasi = request.form.get("lokasi", "").strip() or None
        k.penyelenggara = request.form.get("penyelenggara", "").strip() or None
        k.tanggal_mulai = _parse_dt(request.form.get("tanggal_mulai", ""))
        k.tanggal_selesai = _parse_dt(request.form.get("tanggal_selesai", ""))
        k.status = request.form.get("status", "published")

        f = request.files.get("gambar")
        if f and f.filename:
            path = save_upload(f, "kegiatan", allow_image_only=True)
            if path:
                k.gambar = path
            else:
                flash("Format gambar tidak didukung (gunakan PNG/JPG).", "warning")
        _audit("save_kegiatan", judul[:80])
        db.session.commit()
        flash("Kegiatan disimpan.", "success")
        return redirect(url_for("admin_sosmed.kegiatan_list"))
    return render_template("admin_sosmed/kegiatan_form.html", k=k)


@bp.route("/kegiatan/<int:kid>/delete", methods=["POST"])
def kegiatan_delete(kid):
    k = Kegiatan.query.get_or_404(kid)
    _audit("delete_kegiatan", k.judul[:80])
    db.session.delete(k)
    db.session.commit()
    flash("Kegiatan dihapus.", "success")
    return redirect(url_for("admin_sosmed.kegiatan_list"))


# =====================================================================
# KERJA SAMA
# =====================================================================
@bp.route("/kerjasama")
def kerjasama_list():
    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    query = KerjaSama.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(
            KerjaSama.judul.ilike(like),
            KerjaSama.mitra.ilike(like),
            KerjaSama.kategori.ilike(like),
        ))
    total = query.count()
    rows = (
        query.order_by(KerjaSama.created_at.desc())
        .limit(per_page).offset((page - 1) * per_page).all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "admin_sosmed/kerjasama_list.html",
        rows=rows, q=q, page=page, pages=pages, total=total,
    )


@bp.route("/kerjasama/baru", methods=["GET", "POST"])
@bp.route("/kerjasama/<int:kid>/edit", methods=["GET", "POST"])
def kerjasama_form(kid=None):
    ks = KerjaSama.query.get(kid) if kid else None
    if request.method == "POST":
        judul = request.form.get("judul", "").strip()
        mitra = request.form.get("mitra", "").strip()
        isi = request.form.get("isi", "").strip()
        if not judul or not mitra or not isi:
            flash("Judul, mitra, & isi wajib diisi.", "danger")
            return render_template("admin_sosmed/kerjasama_form.html", ks=ks)

        if ks is None:
            ks = KerjaSama(
                judul=judul, mitra=mitra, isi=isi, penulis_id=current_user.id,
            )
            db.session.add(ks)
        ks.judul = judul
        ks.mitra = mitra
        ks.isi = isi
        ks.ringkasan = request.form.get("ringkasan", "").strip() or None
        ks.kategori = request.form.get("kategori", "Industri").strip() or "Industri"
        ks.masa_berlaku = request.form.get("masa_berlaku", "").strip() or None
        ks.tanggal_mou = _parse_date(request.form.get("tanggal_mou", ""))
        ks.status = request.form.get("status", "published")

        f = request.files.get("logo")
        if f and f.filename:
            path = save_upload(f, "kerjasama", allow_image_only=True)
            if path:
                ks.logo = path
            else:
                flash("Format logo tidak didukung (gunakan PNG/JPG).", "warning")
        _audit("save_kerjasama", judul[:80])
        db.session.commit()
        flash("Kerja sama disimpan.", "success")
        return redirect(url_for("admin_sosmed.kerjasama_list"))
    return render_template("admin_sosmed/kerjasama_form.html", ks=ks)


@bp.route("/kerjasama/<int:kid>/delete", methods=["POST"])
def kerjasama_delete(kid):
    ks = KerjaSama.query.get_or_404(kid)
    _audit("delete_kerjasama", ks.judul[:80])
    db.session.delete(ks)
    db.session.commit()
    flash("Kerja sama dihapus.", "success")
    return redirect(url_for("admin_sosmed.kerjasama_list"))


# =====================================================================
# PENDAFTAR PMB (lead) — view + ubah status
# =====================================================================
@bp.route("/pmb-pendaftar")
def pmb_pendaftar():
    status = request.args.get("status", "")
    query = PendaftaranPMB.query
    if status:
        query = query.filter_by(status=status)
    rows = query.order_by(PendaftaranPMB.created_at.desc()).limit(300).all()
    return render_template(
        "admin_sosmed/pmb_pendaftar.html", rows=rows, status=status,
    )


@bp.route("/pmb-pendaftar/<int:pid>/status", methods=["POST"])
def pmb_pendaftar_status(pid):
    r = PendaftaranPMB.query.get_or_404(pid)
    r.status = request.form.get("status", r.status)
    db.session.commit()
    flash("Status pendaftar diperbarui.", "success")
    return redirect(url_for("admin_sosmed.pmb_pendaftar"))
