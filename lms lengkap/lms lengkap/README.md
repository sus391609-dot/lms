# LMS Universitas Yarsi Pratama

Learning Management System lengkap untuk Universitas Yarsi Pratama.
Multi-role (Mahasiswa, Dosen, Admin, Super Admin), responsif untuk
desktop / tablet / mobile, dengan palet warna dominan oranye
(`#ff5f1a`).

Stack: **Python (Flask) + SQLite + HTML/CSS/JS vanilla**.

---

## Fitur Utama

### Mahasiswa
- Dashboard, jadwal kuliah, daftar tugas (upload PDF/DOCX/PPTX/JPG/PNG max 20 MB)
- KRS (memilih kelas yang dibuka admin)
- Nilai per semester (komponen Kuis 5%, Tugas 10%, UTS 15%, UAS 20%, Keaktifan 20%, Proyek 30%)
- Pembayaran (upload bukti, lihat status)
- Konseling chat ke seluruh dosen (lintas prodi)
- Pemberian poin ke dosen (max 10 poin/semester)
- Profil dosen pengajar, organisasi (read-only)

### Dosen
- Dashboard, daftar matkul yang diampu
- Membuat tugas berbobot (Kuis/Tugas/UTS/UAS/Proyek), menilai jawaban
- Absensi pertemuan dengan checkbox hadir/izin/sakit/alpha + alasan
- Rekap absensi per semester per kelas
- Input nilai berbasis komponen (otomatis dihitung)
- Konseling chat dengan mahasiswa di kelas yang diampu
- Profil dosen

### Admin
- Approval pendaftaran mahasiswa & dosen
- CRUD users, master mata kuliah, plotting dosen, kelas paralel
- Penjadwalan dengan **conflict detector** (dosen/ruangan bentrok otomatis ditolak)
- KRS distribusi massal (bulk enrollment per prodi+semester)
- Buat tagihan & verifikasi pembayaran
- Input keaktifan organisasi mahasiswa
- Reset poin per semester
- Gatekeeping (buka/tutup periode KRS & input nilai)
- Audit log perubahan
- Statistik realtime per prodi (auto-refresh 30s)

### Super Admin
- Manage seluruh user (ubah role & status)
- Kunci/buka seluruh sistem
- Backup database (download `.db`)
- Audit log lengkap

### Auth
- Login terpisah per role (Mahasiswa, Dosen, Admin, Super Admin)
- Halaman PMB untuk guest
- Pendaftaran dengan verifikasi kode email via SMTP Gmail
- Lupa password via kode email
- Domain email dosen wajib `@yarsipratama.ac.id`
- Mahasiswa wajib memilih 1 prodi, dosen sampai 10 prodi

---

## Cara Menjalankan

### 1. Persiapan environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 2. (Opsional) Set env variable SMTP

Aplikasi sudah memiliki kredensial default. Anda dapat override via env:

```bash
export SMTP_USER="akuntugas3916@gmail.com"
export SMTP_PASS="rybwzfprcfmpfzkh"
export SMTP_DISABLED=0   # set ke "1" jika ingin mode offline (kode hanya di-log)
```

### 3. Jalankan server

```bash
python run.py
```

Server berjalan di <http://localhost:5000>. Database SQLite otomatis dibuat
di `instance/lms.db` beserta data seed (8 prodi Yarsi Pratama, akun demo).

---

## Akun Demo

| Role        | Email                                  | Password    |
| ----------- | -------------------------------------- | ----------- |
| Super Admin | superadmin@yarsipratama.ac.id          | super123    |
| Admin       | admin@yarsipratama.ac.id               | admin123    |
| Dosen       | budi.santoso@yarsipratama.ac.id        | dosen123    |
| Mahasiswa   | andi@student.yarsipratama.ac.id        | mhs123      |

Mahasiswa demo (`andi@...`) tergabung di prodi **S1 Teknik Informatika**.

---

## Struktur Folder

```
lms/
├── app/
│   ├── __init__.py            # Flask factory
│   ├── extensions.py          # db, login_manager, csrf
│   ├── models.py              # Semua tabel SQLAlchemy
│   ├── decorators.py          # role_required
│   ├── seed.py                # Data awal
│   ├── utils/
│   │   ├── email.py           # Helper SMTP
│   │   └── files.py           # Helper upload
│   ├── auth/                  # Login, register, verifikasi
│   ├── mahasiswa/             # Routes mahasiswa
│   ├── dosen/                 # Routes dosen
│   ├── admin/                 # Routes admin
│   ├── superadmin/            # Routes super admin
│   ├── pmb/                   # Halaman PMB
│   └── api/                   # Endpoint JSON
├── templates/
│   ├── base.html
│   ├── _dashboard_base.html
│   ├── auth/
│   ├── mahasiswa/
│   ├── dosen/
│   ├── admin/
│   ├── superadmin/
│   ├── pmb/
│   ├── partials/              # Sidebar per role
│   └── errors/
├── static/
│   ├── css/                   # base.css, auth.css
│   ├── js/
│   ├── img/
│   └── uploads/               # Tugas, silabus, pembayaran, profil, jawaban
├── instance/                  # SQLite DB
├── config.py
├── requirements.txt
├── run.py
└── README.md
```

---

## Komponen Penilaian

Total 100% dengan komposisi:

- **Kuis**: 5%
- **Tugas**: 10%
- **UTS**: 15%
- **UAS**: 20%
- **Keaktifan Mahasiswa**: 20%
- **Proyek Inovasi**: 30%

Konversi grade: A (>=85), B (>=75), C (>=65), D (>=55), E (<55).

---

## Catatan Teknis

- Database default: SQLite (`instance/lms.db`).
- Upload file maksimum: 20 MB, ekstensi `.pdf .docx .doc .pptx .ppt .png .jpg .jpeg`.
- Password disimpan dengan bcrypt (Werkzeug `generate_password_hash`).
- CSRF protection aktif di semua form (Flask-WTF).
- Responsif: sidebar collapse menjadi hamburger menu di layar < 768px.
- Email verifikasi mengandung kode 6 digit yang berlaku 15 menit.
