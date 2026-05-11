"""
run.py
======
Entry point untuk menjalankan aplikasi LMS Universitas Yarsi Pratama.

Perintah:
    python run.py            -> menjalankan server development di port 5000

Saat pertama kali dijalankan, aplikasi otomatis membuat database SQLite
di folder ``instance/lms.db`` dan mengisi seed data (prodi, super admin,
admin demo, dosen demo, mahasiswa demo) bila DB masih kosong.
"""
from app import create_app
from app.seed import run_seed

# Buat instance Flask app menggunakan factory pattern
app = create_app()

if __name__ == "__main__":
    # Pastikan tabel + seed data tersedia sebelum server dijalankan
    with app.app_context():
        run_seed()
    # host 0.0.0.0 supaya bisa diakses dari LAN (mis. testing di mobile)
    app.run(host="0.0.0.0", port=5000, debug=True)
