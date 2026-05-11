"""
app/decorators.py
=================
Helper decorator untuk membatasi akses route berdasarkan role.

Contoh::

    @bp.route("/dashboard")
    @login_required
    @role_required("mahasiswa")
    def dashboard():
        ...
"""
from functools import wraps

from flask import abort
from flask_login import current_user


def role_required(*roles):
    """Hanya izinkan user dengan ``role`` yang tercantum."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            if current_user.status != "aktif":
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
