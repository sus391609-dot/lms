"""
app/pmb/routes.py
=================
Halaman Penerimaan Mahasiswa Baru (PMB) untuk guest. Tidak butuh login.
Berisi info prodi yang dibuka & link ke pendaftaran mahasiswa.
"""
from flask import Blueprint, render_template

from app.models import ProgramStudi

bp = Blueprint("pmb", __name__)


@bp.route("/")
def index():
    prodi_list = ProgramStudi.query.all()
    return render_template("pmb/index.html", prodi_list=prodi_list)
