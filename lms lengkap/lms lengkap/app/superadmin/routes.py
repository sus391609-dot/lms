"""
app/superadmin/routes.py
========================
Akses penuh untuk super admin:
- Lihat seluruh statistik universitas.
- Manage role & hak akses (promote/demote user).
- Backup & download database SQLite.
- Lock/unlock seluruh sistem (memblokir akses semua role kecuali superadmin).
- Manipulasi data semua user.
"""
import csv
import io
import os
import shutil
import zipfile
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    send_from_directory, send_file, current_app,
)
from flask_login import login_required, current_user
from sqlalchemy import inspect

from app.extensions import db
from app.models import (
    User, ProgramStudi, ProfilMahasiswa, ProfilDosen,
    AuditLog, SystemSetting, LoginActivity,
)
from app.utils import save_upload
from app.utils import record_audit

bp = Blueprint("superadmin", __name__)


@bp.before_request
@login_required
def _require_superadmin():
    if current_user.role != "superadmin" or current_user.status != "aktif":
        abort(403)


@bp.route("/")
@bp.route("/dashboard")
def dashboard():
    counts = {
        "users": User.query.count(),
        "mahasiswa": User.query.filter_by(role="mahasiswa").count(),
        "dosen": User.query.filter_by(role="dosen").count(),
        "admin": User.query.filter_by(role="admin").count(),
        "prodi": ProgramStudi.query.count(),
        "login_total": LoginActivity.query.count(),
    }
    locked = SystemSetting.get("system_locked", "0") == "1"
    audits = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()
    return render_template(
        "superadmin/dashboard.html", counts=counts, locked=locked, audits=audits,
    )


@bp.route("/users")
def users():
    users = User.query.order_by(User.role, User.nama).all()
    return render_template("superadmin/users.html", users=users)


@bp.route("/users/<int:uid>/role", methods=["POST"])
def change_role(uid):
    u = User.query.get_or_404(uid)
    new_role = request.form.get("role")
    if new_role in ("mahasiswa", "dosen", "admin", "superadmin"):
        u.role = new_role
        record_audit("change_role", target=str(u.id), detail=new_role)
        db.session.commit()
        flash(f"Role {u.email} -> {new_role}.", "info")
    return redirect(url_for("superadmin.users"))


@bp.route("/users/<int:uid>/status", methods=["POST"])
def change_status(uid):
    u = User.query.get_or_404(uid)
    s = request.form.get("status")
    if s in ("aktif", "nonaktif", "pending", "ditolak"):
        u.status = s
        record_audit("change_status", target=str(u.id), detail=s)
        db.session.commit()
        flash(f"Status {u.email} -> {s}.", "info")
    return redirect(url_for("superadmin.users"))


@bp.route("/system", methods=["GET", "POST"])
def system():
    if request.method == "POST":
        SystemSetting.set("system_locked",
                          "1" if request.form.get("system_locked") else "0")
        record_audit("toggle_system_lock",
                     detail=SystemSetting.get("system_locked"))
        db.session.commit()
        flash("Status sistem disimpan.", "info")
        return redirect(url_for("superadmin.system"))
    locked = SystemSetting.get("system_locked", "0") == "1"
    return render_template("superadmin/system.html", locked=locked)


@bp.route("/backup")
def backup():
    """Salin file SQLite ke folder backups/ lalu kirim ke browser."""
    src = os.path.join(current_app.instance_path, "lms.db")
    backup_dir = os.path.join(current_app.root_path, "..", "backups")
    backup_dir = os.path.abspath(backup_dir)
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    dst_name = f"lms-backup-{ts}.db"
    dst = os.path.join(backup_dir, dst_name)
    if os.path.exists(src):
        shutil.copyfile(src, dst)
        record_audit("backup_db", detail=dst_name)
        db.session.commit()
        return send_from_directory(backup_dir, dst_name, as_attachment=True)
    flash("Database tidak ditemukan.", "danger")
    return redirect(url_for("superadmin.dashboard"))


@bp.route("/export")
def export():
    """Halaman tombol export (CSV ZIP) + link backup DB."""
    tables = [t for t in db.metadata.sorted_tables]
    return render_template("superadmin/system.html", tables=tables, view="export")


@bp.route("/export/all.zip")
def export_all_zip():
    """Dump seluruh tabel ke CSV, bundel jadi satu ZIP siap unduh."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in db.metadata.sorted_tables:
            rows = db.session.execute(table.select()).mappings().all()
            csv_buf = io.StringIO()
            if rows:
                writer = csv.DictWriter(csv_buf, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
            else:
                # Tetap tulis header walau tabel kosong
                cols = [c.name for c in table.columns]
                csv_buf.write(",".join(cols) + "\n")
            zf.writestr(f"{table.name}.csv", csv_buf.getvalue())

        # Sertakan juga file .db sebagai backup lengkap
        src_db = os.path.join(current_app.instance_path, "lms.db")
        if os.path.exists(src_db):
            zf.write(src_db, arcname="lms.db")

        # Manifest
        manifest = (
            f"LMS Universitas Yarsi Pratama — Export\n"
            f"Waktu: {datetime.utcnow().isoformat()}Z\n"
            f"Diunduh oleh: {current_user.email}\n"
            f"Tabel: {len(db.metadata.sorted_tables)}\n"
        )
        zf.writestr("MANIFEST.txt", manifest)

    record_audit("export_all",
                 detail=f"{len(db.metadata.sorted_tables)} tables")
    db.session.commit()

    buf.seek(0)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"lms-export-{ts}.zip",
    )


@bp.route("/export/<table_name>.csv")
def export_table_csv(table_name):
    """Export satu tabel ke CSV."""
    table = db.metadata.tables.get(table_name)
    if table is None:
        abort(404)
    rows = db.session.execute(table.select()).mappings().all()
    buf = io.StringIO()
    cols = [c.name for c in table.columns]
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    data = buf.getvalue().encode("utf-8")

    record_audit("export_table", target=table_name)
    db.session.commit()

    return send_file(
        io.BytesIO(data), mimetype="text/csv", as_attachment=True,
        download_name=f"{table_name}.csv",
    )


@bp.route("/audit")
def audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template("superadmin/system.html", logs=logs, view="audit")


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
        return redirect(url_for("superadmin.profile"))
    return render_template("superadmin/profile.html")


