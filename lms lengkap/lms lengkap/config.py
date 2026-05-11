"""
config.py
=========
Konfigurasi global aplikasi LMS Universitas Yarsi Pratama.

Semua konstanta yang berhubungan dengan environment (database, SMTP,
upload, dsb.) dipisah ke sini agar mudah diubah tanpa menyentuh kode
business logic.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # ---- Flask core ----
    SECRET_KEY = os.environ.get("SECRET_KEY", "CHANGE-ME-BEFORE-RUNNING")

    # ---- Database (SQLite) ----
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "lms.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ---- SMTP Gmail (kirim kode verifikasi & lupa password) ----
    # NB: kredensial dapat di-override via env var di production.
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")           # isi via .env
    # Mendukung dua nama env: SMTP_PASS atau SMTP_APP_PASSWORD.
    SMTP_PASS = (
        os.environ.get("SMTP_APP_PASSWORD")
        or os.environ.get("SMTP_PASS")
        or ""
    )
    SMTP_FROM = os.environ.get("SMTP_FROM", "")            # isi via .env
    # Bila True, kode verifikasi hanya di-print ke console (mode offline / CI).
    SMTP_DISABLED = os.environ.get("SMTP_DISABLED", "0") == "1"

    # ---- Upload tugas / silabus / bukti pembayaran ----
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024  # 20 MB
    ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "pptx", "ppt", "png", "jpg", "jpeg"}

    # ---- Domain email khusus dosen ----
    DOSEN_EMAIL_DOMAIN = "yarsipratama.ac.id"

    # ---- Aturan poin ----
    POIN_PER_SEMESTER = 10  # poin maksimum yang dapat diberikan mahasiswa ke dosen

    # ---- Bobot komponen nilai (total = 100) ----
    # Kuis 5 + Tugas 10 + UTS 15 + UAS 20 + Keaktifan 20 + Proyek 30 = 100
    BOBOT_NILAI = {
        "kuis": 5,
        "tugas": 10,
        "uts": 15,
        "uas": 20,
        "keaktifan": 20,
        "proyek": 30,
    }
