"""
app/__init__.py
===============
Flask application factory untuk LMS Universitas Yarsi Pratama.

Cara penggunaan:
    from app import create_app
    app = create_app()
"""
import os

from flask import Flask, render_template, redirect, url_for
from flask_login import current_user

from config import Config
from app.extensions import db, login_manager, csrf


def create_app(config_class=Config):
    """Buat dan konfigurasi instance Flask."""
    app = Flask(
        __name__,
        template_folder=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "templates"
        ),
        static_folder=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "static"
        ),
    )
    app.config.from_object(config_class)

    # ── Init extensions ────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # ── User loader ────────────────────────────────────────────────────
    from app.models import User

    @login_manager.user_loader
    def load_user(uid):
        return User.query.get(int(uid))

    # ── Register blueprints ────────────────────────────────────────────
    from app.public.routes import bp as public_bp
    app.register_blueprint(public_bp)

    from app.auth.routes import bp as auth_bp
    app.register_blueprint(auth_bp)

    from app.admin.routes import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from app.admin_sosmed.routes import bp as admin_sosmed_bp
    app.register_blueprint(admin_sosmed_bp, url_prefix="/sosmed")

    from app.dosen.routes import bp as dosen_bp
    app.register_blueprint(dosen_bp, url_prefix="/dosen")

    from app.mahasiswa.routes import bp as mahasiswa_bp
    app.register_blueprint(mahasiswa_bp, url_prefix="/mahasiswa")

    from app.superadmin.routes import bp as superadmin_bp
    app.register_blueprint(superadmin_bp, url_prefix="/superadmin")

    from app.pmb.routes import bp as pmb_bp
    app.register_blueprint(pmb_bp, url_prefix="/pmb")

    from app.api.routes import bp as api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    # ── System-lock guard ──────────────────────────────────────────────
    @app.before_request
    def check_system_lock():
        from flask import request
        from app.models import SystemSetting
        if SystemSetting.get("system_locked", "0") != "1":
            return None
        # Superadmin & login/static boleh lewat
        if current_user.is_authenticated and current_user.role == "superadmin":
            return None
        if request.endpoint in ("auth.landing", "auth.logout", "static"):
            return None
        # Public website tetap dapat diakses meski sistem dikunci.
        if request.endpoint and request.endpoint.startswith("public."):
            return None
        return render_template(
            "errors/error.html",
            code="locked",
            message="Sistem LMS sedang ditutup sementara untuk pemeliharaan. "
                    "Silakan coba lagi nanti.",
        )

    # ── Context processor ──────────────────────────────────────────────
    @app.context_processor
    def inject_globals():
        from datetime import datetime
        return {
            "app_name": "LMS Universitas Yarsi Pratama",
            "now": datetime.utcnow(),
        }

    # ── Jinja filters ──────────────────────────────────────────────────
    from datetime import date, datetime as _dt

    BULAN_ID = [
        "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    ]

    @app.template_filter("tgl_id")
    def _tgl_id(value):
        """Format date / datetime ke Bahasa Indonesia.

        - ``date``        → "12 Mei 2025"
        - ``datetime``    → "12 Mei 2025, 14:30"
        - lainnya / None  → "-"
        """
        if value is None:
            return "-"
        if isinstance(value, _dt):
            return f"{value.day} {BULAN_ID[value.month]} {value.year}, {value.strftime('%H:%M')}"
        if isinstance(value, date):
            return f"{value.day} {BULAN_ID[value.month]} {value.year}"
        return str(value)

    @app.template_filter("rupiah")
    def _rupiah(value):
        """Format angka jadi 'Rp 1.234.567'."""
        try:
            n = int(round(float(value or 0)))
        except (TypeError, ValueError):
            return "Rp 0"
        sign = "-" if n < 0 else ""
        s = f"{abs(n):,}".replace(",", ".")
        return f"{sign}Rp {s}"

    # ── Error handlers ─────────────────────────────────────────────────
    @app.errorhandler(400)
    def bad_request(e):
        return render_template(
            "errors/error.html", code=400,
            message="Permintaan tidak valid."
        ), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return redirect(url_for("auth.landing"))

    @app.errorhandler(403)
    def forbidden(e):
        return render_template(
            "errors/error.html", code=403,
            message="Akses ditolak. Anda tidak memiliki izin."
        ), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template(
            "errors/error.html", code=404,
            message="Halaman tidak ditemukan."
        ), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template(
            "errors/error.html", code=413,
            message="File terlalu besar. Maksimum upload adalah 20 MB."
        ), 413

    @app.errorhandler(500)
    def server_error(e):
        return render_template(
            "errors/error.html", code=500,
            message="Terjadi kesalahan internal pada server."
        ), 500

    # ── Create DB tables ───────────────────────────────────────────────
    with app.app_context():
        db.create_all()

    return app
