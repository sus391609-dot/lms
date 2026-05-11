"""
app/seed.py
===========
Inisialisasi DB + data awal: prodi Yarsi Pratama, super admin, admin
demo, dosen demo, mahasiswa demo, beberapa mata kuliah, kelas, jadwal,
dan tagihan pembayaran.

Dipanggil otomatis dari ``run.py`` saat aplikasi start, hanya akan
menambah data bila tabel ``users`` masih kosong.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import (
    User, ProgramStudi, ProfilMahasiswa, ProfilDosen,
    MataKuliah, Kelas, Jadwal, KRS, Pembayaran, SystemSetting, Nilai,
    KonselingThread, Materi, Portfolio,
)


PRODI_YARSI = [
    ("D3 Kebidanan", "Fakultas Ilmu Kesehatan"),
    ("D3 Radiologi", "Fakultas Ilmu Kesehatan"),
    ("S1 Ilmu Gizi", "Fakultas Ilmu Kesehatan"),
    ("S1 Administrasi Kesehatan", "Fakultas Ilmu Kesehatan"),
    ("S1 Manajemen", "FTBH"),
    ("S1 Hukum", "FTBH"),
    ("S1 Teknik Informatika", "FTBH"),
    ("S1 Ilmu Komunikasi", "FTBH"),
]


def _sqlite_ensure_columns() -> None:
    """Tambah kolom baru secara idempotent pada DB SQLite existing.

    SQLAlchemy ``create_all()`` hanya membuat tabel baru; kolom baru pada
    tabel yang sudah ada tidak ikut. Untuk LMS ini kita memilih pendekatan
    ringan tanpa Alembic: jalankan ALTER TABLE ADD COLUMN bila kolom
    belum ada. Cocok untuk SQLite.
    """
    from sqlalchemy import text, inspect as sa_inspect

    bind = db.session.get_bind()
    if bind.dialect.name != "sqlite":
        return  # untuk engine lain biarkan alembic yang urus

    insp = sa_inspect(bind)
    specs = {
        "konseling_thread": {
            "status": "VARCHAR(16) NOT NULL DEFAULT 'pending'",
            "opened_by": "VARCHAR(16)",
            "accepted_at": "DATETIME",
            "ended_at": "DATETIME",
            "ended_by": "VARCHAR(16)",
            "deleted_by_mhs": "BOOLEAN NOT NULL DEFAULT 0",
            "deleted_by_dosen": "BOOLEAN NOT NULL DEFAULT 0",
        },
    }
    for tbl, cols in specs.items():
        if tbl not in insp.get_table_names():
            continue
        existing = {c["name"] for c in insp.get_columns(tbl)}
        for col_name, col_type in cols.items():
            if col_name in existing:
                continue
            db.session.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}"))
    db.session.commit()

    # ---------------------------------------------------------------
    # DROP legacy UNIQUE constraint pada konseling_thread (mahasiswa_id,
    # dosen_id). Constraint ini pernah ada di versi awal; sekarang satu
    # pasang user dapat memiliki banyak tiket terpisah (history vs aktif).
    # SQLite tidak mendukung DROP CONSTRAINT langsung, jadi kita rebuild
    # tabel jika constraint masih ada.
    # ---------------------------------------------------------------
    if "konseling_thread" in insp.get_table_names():
        # Deteksi UNIQUE lama lewat: (a) CREATE TABLE sql yg memuat
        # "UNIQUE" atau "uq_konseling", atau (b) index unik di
        # sqlite_master (termasuk sqlite_autoindex dari UNIQUE constraint).
        tbl_sql_row = db.session.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='konseling_thread'"
        )).fetchone()
        tbl_sql = (tbl_sql_row[0] if tbl_sql_row else "") or ""
        has_legacy = "uq_konseling" in tbl_sql.lower() or (
            "unique" in tbl_sql.lower()
            and "konseling_thread" in tbl_sql.lower()
            and "mahasiswa_id" in tbl_sql.lower()
            and "dosen_id" in tbl_sql.lower()
        )
        if has_legacy:
            # Rebuild dgn schema yg benar dari model (PK, types, autoincrement,
            # default) lalu copy data dari tabel lama.
            old_cols = [c["name"] for c in insp.get_columns("konseling_thread")]
            model_cols = [c.name for c in KonselingThread.__table__.columns]
            shared = [c for c in old_cols if c in model_cols]
            shared_csv = ", ".join(shared)

            db.session.execute(text("PRAGMA foreign_keys=OFF"))
            db.session.commit()
            db.session.execute(text(
                "ALTER TABLE konseling_thread RENAME TO konseling_thread_legacy"
            ))
            db.session.commit()
            # Create tabel baru dari definisi SQLAlchemy model.
            KonselingThread.__table__.create(bind=bind)
            db.session.execute(text(
                f"INSERT INTO konseling_thread ({shared_csv}) "
                f"SELECT {shared_csv} FROM konseling_thread_legacy"
            ))
            db.session.execute(text("DROP TABLE konseling_thread_legacy"))
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()


def run_seed() -> None:
    db.create_all()
    _sqlite_ensure_columns()

    # Default settings
    if not SystemSetting.get("krs_open"):
        SystemSetting.set("krs_open", "1")
    if not SystemSetting.get("nilai_open"):
        SystemSetting.set("nilai_open", "1")
    if not SystemSetting.get("system_locked"):
        SystemSetting.set("system_locked", "0")

    # Prodi
    if ProgramStudi.query.count() == 0:
        for nama, fak in PRODI_YARSI:
            db.session.add(ProgramStudi(nama=nama, fakultas=fak))
        db.session.commit()

    if User.query.count() > 0:
        return  # sudah pernah di-seed

    # ---- Super Admin ----
    sa = User(
        nama="Super Administrator",
        email="superadmin@yarsipratama.ac.id",
        role="superadmin",
        status="aktif",
        email_verified=True,
    )
    sa.set_password("super123")
    db.session.add(sa)

    # ---- Admin demo ----
    admin = User(
        nama="Admin Akademik",
        email="admin@yarsipratama.ac.id",
        role="admin",
        status="aktif",
        email_verified=True,
    )
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()

    # ---- Dosen demo ----
    prodi_ti = ProgramStudi.query.filter_by(nama="S1 Teknik Informatika").first()
    prodi_mn = ProgramStudi.query.filter_by(nama="S1 Manajemen").first()

    dosen = User(
        nama="Dr. Budi Santoso, S.Kom., M.T.",
        email="budi.santoso@yarsipratama.ac.id",
        role="dosen",
        status="aktif",
        email_verified=True,
    )
    dosen.set_password("dosen123")
    db.session.add(dosen)
    db.session.commit()

    pd = ProfilDosen(user_id=dosen.id, nidn="0301018501", jabatan="Lektor")
    pd.prodi_list = [prodi_ti, prodi_mn]
    db.session.add(pd)

    # ---- Mahasiswa demo ----
    mhs = User(
        nama="Andi Mahasiswa",
        email="andi@student.yarsipratama.ac.id",
        role="mahasiswa",
        status="aktif",
        email_verified=True,
    )
    mhs.set_password("mhs123")
    db.session.add(mhs)
    db.session.commit()

    db.session.add(ProfilMahasiswa(
        user_id=mhs.id, nim="2024010001",
        prodi_id=prodi_ti.id, angkatan=2024, semester=1,
    ))

    # ---- Mata Kuliah ----
    mk1 = MataKuliah(
        kode="TI101", nama="Algoritma & Pemrograman",
        rumpun="Informatika", sks=3, jenis="wajib",
        prodi_id=prodi_ti.id, semester=1,
    )
    mk2 = MataKuliah(
        kode="TI102", nama="Pengantar Sistem Informasi",
        rumpun="Informatika", sks=3, jenis="wajib",
        prodi_id=prodi_ti.id, semester=1,
    )
    db.session.add_all([mk1, mk2])
    db.session.commit()

    # ---- Kelas + Jadwal ----
    k1 = Kelas(matkul_id=mk1.id, dosen_id=dosen.id, kode_kelas="A", kuota=40)
    k2 = Kelas(matkul_id=mk2.id, dosen_id=dosen.id, kode_kelas="A", kuota=40)
    db.session.add_all([k1, k2])
    db.session.commit()

    db.session.add_all([
        Jadwal(kelas_id=k1.id, hari="Senin", jam_mulai="08:00",
               jam_selesai="10:30", ruangan="R-101"),
        Jadwal(kelas_id=k2.id, hari="Selasa", jam_mulai="10:30",
               jam_selesai="13:00", ruangan="R-102"),
    ])

    # ---- KRS demo ----
    db.session.add_all([
        KRS(mahasiswa_id=mhs.id, kelas_id=k1.id, semester=1),
        KRS(mahasiswa_id=mhs.id, kelas_id=k2.id, semester=1),
    ])

    # ---- Pembayaran demo ----
    db.session.add(Pembayaran(
        mahasiswa_id=mhs.id, judul="UKT Semester 1",
        nominal=5_000_000, semester=1,
        status="belum_bayar",
    ))

    # ---- Organisasi demo (biar dosen/admin bisa lihat) ----
    pm = ProfilMahasiswa.query.filter_by(user_id=mhs.id).first()
    if pm:
        pm.organisasi = (
            "HIMATI — Divisi Akademik (2024)\n"
            "BEM Fakultas — Staf Humas (2025)"
        )

    # ---- Nilai demo (biar admin bisa demo override & dosen bisa lihat) ----
    n1 = Nilai(
        kelas_id=k1.id, mahasiswa_id=mhs.id, semester=1,
        nilai_kuis=82, nilai_tugas=78, nilai_uts=75,
        nilai_uas=80, nilai_keaktifan=85, nilai_proyek=88,
    )
    n1.hitung()
    n2 = Nilai(
        kelas_id=k2.id, mahasiswa_id=mhs.id, semester=1,
        nilai_kuis=70, nilai_tugas=72, nilai_uts=68,
        nilai_uas=74, nilai_keaktifan=80, nilai_proyek=82,
    )
    n2.hitung()
    db.session.add_all([n1, n2])

    # No Telp & alamat demo pada user supaya halaman kontak terisi.
    mhs.no_telp = "0812-3456-7890"
    mhs.alamat = "Jl. Letjen Suprapto No. 1, Jakarta Pusat"
    dosen.no_telp = "0811-2233-4455"

    # ---- Materi demo (konten belajar + YouTube) ----
    db.session.add_all([
        Materi(
            kelas_id=k1.id, judul="Pengantar Algoritma",
            deskripsi="Materi pengantar tentang dasar-dasar algoritma dan flowchart.",
            youtube_url="https://www.youtube.com/watch?v=rL8X2mlNHPM",
            urutan=1,
        ),
        Materi(
            kelas_id=k1.id, judul="Variabel & Tipe Data",
            deskripsi="Pembahasan tentang variabel, tipe data, dan operator di Python.",
            youtube_url="https://www.youtube.com/watch?v=kqtD5dpn9C8",
            urutan=2,
        ),
        Materi(
            kelas_id=k2.id, judul="Apa itu Sistem Informasi?",
            deskripsi="Pengenalan konsep sistem informasi dan komponen-komponennya.",
            youtube_url="https://www.youtube.com/watch?v=Qujsd4vkqFI",
            urutan=1,
        ),
    ])

    # ---- Portfolio demo ----
    db.session.add_all([
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Juara 1 Hackathon Nasional",
            kategori="prestasi",
            deskripsi="Memenangkan kompetisi hackathon nasional yang diselenggarakan oleh Kementerian Kominfo.",
            tahun=2024,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Aplikasi Mobile E-Health",
            kategori="karya",
            deskripsi="Membangun aplikasi mobile berbasis Flutter untuk membantu tracking kesehatan.",
            tahun=2024,
        ),
    ])

    db.session.commit()
