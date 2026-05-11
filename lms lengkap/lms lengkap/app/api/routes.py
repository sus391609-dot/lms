"""
app/api/routes.py
=================
Endpoint JSON ringan untuk polling (notifikasi, statistik dashboard,
chat konseling). Tidak digunakan untuk autentikasi.
"""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (
    Notifikasi, KonselingThread, KonselingPesan, LoginActivity, ProgramStudi,
)

bp = Blueprint("api", __name__)


@bp.route("/notifikasi")
@login_required
def notifikasi():
    rows = (
        Notifikasi.query.filter_by(user_id=current_user.id)
        .order_by(Notifikasi.created_at.desc()).limit(20).all()
    )
    return jsonify([
        {
            "id": n.id, "judul": n.judul, "isi": n.isi,
            "dibaca": n.dibaca, "created_at": n.created_at.isoformat(),
        } for n in rows
    ])


@bp.route("/konseling/<int:tid>/pesan")
@login_required
def konseling_pesan(tid):
    th = KonselingThread.query.get_or_404(tid)
    if current_user.id not in (th.mahasiswa_id, th.dosen_id):
        return jsonify({"error": "forbidden"}), 403
    rows = (
        KonselingPesan.query.filter_by(thread_id=tid)
        .order_by(KonselingPesan.created_at.asc()).all()
    )
    return jsonify([
        {
            "id": p.id, "isi": p.isi, "sender_id": p.sender_id,
            "sender_nama": p.sender.nama,
            "is_self": p.sender_id == current_user.id,
            "created_at": p.created_at.isoformat(),
        } for p in rows
    ])


@bp.route("/stats/login")
def stats_login():
    """Stats per prodi (publik untuk dashboard chart)."""
    data = []
    for p in ProgramStudi.query.all():
        data.append({
            "prodi": p.nama,
            "login": LoginActivity.query.filter_by(prodi_id=p.id).count(),
        })
    return jsonify(data)
