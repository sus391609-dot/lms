"""
app/public/routes.py
====================
Public-facing website Universitas Yarsi Pratama.

Halaman: Home, Tentang, Berita (list + detail), Kegiatan (list + detail),
Kerja Sama (list + detail), PMB. Tidak memerlukan login. Data statistik
mahasiswa / dosen / prodi diambil langsung dari database LMS.
"""
from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)

from app.extensions import db
from app.models import (
    User, ProgramStudi, Berita, Kegiatan, KerjaSama, PendaftaranPMB,
)

bp = Blueprint("public", __name__)


# ─────────────────────────────────────────────────────────────────────
# Helper statistik kampus (digunakan navbar/home/footer)
# ─────────────────────────────────────────────────────────────────────
def _stats() -> dict:
    return {
        "mahasiswa": User.query.filter_by(role="mahasiswa", status="aktif").count(),
        "dosen": User.query.filter_by(role="dosen", status="aktif").count(),
        "prodi": ProgramStudi.query.count(),
        "fakultas": db.session.query(ProgramStudi.fakultas).distinct().count(),
    }


# =====================================================================
# HOME
# =====================================================================
@bp.route("/")
def home():
    berita_terbaru = (
        Berita.query.filter_by(status="published")
        .order_by(Berita.published_at.desc()).limit(3).all()
    )
    kegiatan_terbaru = (
        Kegiatan.query.filter_by(status="published")
        .order_by(Kegiatan.created_at.desc()).limit(3).all()
    )
    kerjasama_unggulan = (
        KerjaSama.query.filter_by(status="published")
        .order_by(KerjaSama.created_at.desc()).limit(6).all()
    )
    prodi_list = ProgramStudi.query.order_by(ProgramStudi.fakultas, ProgramStudi.nama).all()
    fakultas_map: dict[str, list] = {}
    for p in prodi_list:
        fakultas_map.setdefault(p.fakultas, []).append(p)
    return render_template(
        "public/home.html",
        stats=_stats(),
        berita_terbaru=berita_terbaru,
        kegiatan_terbaru=kegiatan_terbaru,
        kerjasama_unggulan=kerjasama_unggulan,
        fakultas_map=fakultas_map,
    )


@bp.route("/tentang")
def tentang():
    prodi_list = ProgramStudi.query.order_by(ProgramStudi.fakultas, ProgramStudi.nama).all()
    fakultas_map: dict[str, list] = {}
    for p in prodi_list:
        fakultas_map.setdefault(p.fakultas, []).append(p)
    return render_template(
        "public/tentang.html",
        stats=_stats(),
        fakultas_map=fakultas_map,
    )


# =====================================================================
# BERITA
# =====================================================================
@bp.route("/berita")
def berita_list():
    q = request.args.get("q", "").strip()
    kategori = request.args.get("kategori", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 9

    query = Berita.query.filter_by(status="published")
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Berita.judul.ilike(like), Berita.ringkasan.ilike(like))
        )
    if kategori:
        query = query.filter(Berita.kategori == kategori)

    total = query.count()
    rows = (
        query.order_by(Berita.published_at.desc())
        .limit(per_page).offset((page - 1) * per_page).all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    kategori_list = [
        k[0] for k in
        db.session.query(Berita.kategori).filter(Berita.kategori.isnot(None)).distinct().all()
    ]
    return render_template(
        "public/berita_list.html",
        stats=_stats(),
        berita_list=rows,
        kategori_list=kategori_list,
        q=q, kategori=kategori,
        page=page, pages=pages, total=total,
    )


@bp.route("/berita/<int:bid>")
def berita_detail(bid):
    berita = Berita.query.get_or_404(bid)
    if berita.status != "published":
        abort(404)
    berita.views = (berita.views or 0) + 1
    db.session.commit()
    terkait = (
        Berita.query.filter(Berita.id != berita.id, Berita.status == "published")
        .order_by(Berita.published_at.desc()).limit(4).all()
    )
    return render_template(
        "public/berita_detail.html",
        stats=_stats(),
        berita=berita,
        terkait=terkait,
    )


# =====================================================================
# KEGIATAN
# =====================================================================
@bp.route("/kegiatan")
def kegiatan_list():
    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 9

    query = Kegiatan.query.filter_by(status="published")
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Kegiatan.judul.ilike(like), Kegiatan.ringkasan.ilike(like))
        )
    total = query.count()
    rows = (
        query.order_by(Kegiatan.tanggal_mulai.desc().nullslast(), Kegiatan.created_at.desc())
        .limit(per_page).offset((page - 1) * per_page).all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "public/kegiatan_list.html",
        stats=_stats(),
        kegiatan_list=rows,
        q=q, page=page, pages=pages, total=total,
    )


@bp.route("/kegiatan/<int:kid>")
def kegiatan_detail(kid):
    keg = Kegiatan.query.get_or_404(kid)
    if keg.status != "published":
        abort(404)
    keg.views = (keg.views or 0) + 1
    db.session.commit()
    terkait = (
        Kegiatan.query.filter(Kegiatan.id != keg.id, Kegiatan.status == "published")
        .order_by(Kegiatan.created_at.desc()).limit(4).all()
    )
    return render_template(
        "public/kegiatan_detail.html",
        stats=_stats(),
        kegiatan=keg,
        terkait=terkait,
    )


# =====================================================================
# KERJA SAMA
# =====================================================================
@bp.route("/kerjasama")
def kerjasama_list():
    q = request.args.get("q", "").strip()
    kategori = request.args.get("kategori", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 12

    query = KerjaSama.query.filter_by(status="published")
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(KerjaSama.judul.ilike(like), KerjaSama.mitra.ilike(like),
                   KerjaSama.ringkasan.ilike(like))
        )
    if kategori:
        query = query.filter(KerjaSama.kategori == kategori)

    total = query.count()
    rows = (
        query.order_by(KerjaSama.created_at.desc())
        .limit(per_page).offset((page - 1) * per_page).all()
    )
    pages = max(1, (total + per_page - 1) // per_page)
    kategori_list = [
        k[0] for k in
        db.session.query(KerjaSama.kategori).filter(KerjaSama.kategori.isnot(None)).distinct().all()
    ]
    return render_template(
        "public/kerjasama_list.html",
        stats=_stats(),
        kerjasama_list=rows,
        kategori_list=kategori_list,
        q=q, kategori=kategori,
        page=page, pages=pages, total=total,
    )


@bp.route("/kerjasama/<int:kid>")
def kerjasama_detail(kid):
    ks = KerjaSama.query.get_or_404(kid)
    if ks.status != "published":
        abort(404)
    terkait = (
        KerjaSama.query.filter(KerjaSama.id != ks.id, KerjaSama.status == "published")
        .order_by(KerjaSama.created_at.desc()).limit(4).all()
    )
    return render_template(
        "public/kerjasama_detail.html",
        stats=_stats(),
        ks=ks,
        terkait=terkait,
    )


# =====================================================================
# PMB - Informasi & Pendaftaran
# =====================================================================
@bp.route("/pmb", methods=["GET", "POST"])
def pmb():
    prodi_list = ProgramStudi.query.order_by(ProgramStudi.fakultas, ProgramStudi.nama).all()
    fakultas_map: dict[str, list] = {}
    for p in prodi_list:
        fakultas_map.setdefault(p.fakultas, []).append(p)

    submitted = False
    if request.method == "POST":
        try:
            data = PendaftaranPMB(
                nama_lengkap=request.form.get("nama_lengkap", "").strip(),
                email=request.form.get("email", "").strip().lower(),
                no_telp=request.form.get("no_telp", "").strip(),
                asal_sekolah=request.form.get("asal_sekolah", "").strip() or None,
                prodi_id=int(request.form.get("prodi_id")),
                jalur=request.form.get("jalur", "Reguler"),
                catatan=request.form.get("catatan", "").strip() or None,
            )
            if not data.nama_lengkap or not data.email or not data.no_telp:
                flash("Mohon lengkapi nama, email, dan no telp.", "danger")
            else:
                db.session.add(data)
                db.session.commit()
                flash(
                    "Pendaftaran berhasil dikirim! Tim PMB akan menghubungi Anda "
                    "via email/WhatsApp. Anda juga dapat membuat akun mahasiswa.",
                    "success",
                )
                submitted = True
        except (ValueError, TypeError):
            flash("Data tidak valid. Mohon periksa kembali.", "danger")

    return render_template(
        "public/pmb.html",
        stats=_stats(),
        prodi_list=prodi_list,
        fakultas_map=fakultas_map,
        submitted=submitted,
        now=datetime.utcnow(),
    )
