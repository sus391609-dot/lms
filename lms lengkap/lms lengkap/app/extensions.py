"""
app/extensions.py
=================
Tempat menginstansiasi extension Flask agar bisa di-import dari mana saja
tanpa membentuk circular import.

- ``db``           : SQLAlchemy ORM
- ``login_manager``: Flask-Login session manager
- ``csrf``         : CSRF protection (Flask-WTF)
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

# Halaman default ketika user belum login dan mengakses halaman protected.
login_manager.login_view = "auth.landing"
login_manager.login_message = "Silakan login terlebih dahulu."
login_manager.login_message_category = "warning"
