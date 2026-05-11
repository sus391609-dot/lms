"""
app/pmb/routes.py
=================
Halaman PMB lama (kompatibilitas mundur). Sekarang redirect ke
``public.pmb`` yang berisi tampilan modern lengkap (beasiswa, brosur,
syarat pendaftaran, formulir daftar sekarang).
"""
from flask import Blueprint, redirect, url_for

bp = Blueprint("pmb", __name__)


@bp.route("/")
def index():
    return redirect(url_for("public.pmb"))
