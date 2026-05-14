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
    Berita, Kegiatan, KerjaSama,
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

    # ---- Admin Sosmed (CMS / konten publik) ----
    admin_sosmed = User(
        nama="Admin Sosmed UYP",
        email="sosmed@yarsipratama.ac.id",
        role="admin_sosmed",
        status="aktif",
        email_verified=True,
    )
    admin_sosmed.set_password("sosmed123")
    db.session.add(admin_sosmed)
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
            judul="Juara 1 Hackathon Nasional Kominfo 2024",
            kategori="prestasi",
            deskripsi="Memenangkan kompetisi hackathon nasional yang diselenggarakan oleh Kementerian Kominfo dengan proyek aplikasi AI untuk UMKM.",
            tahun=2024,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Best Paper Award — Konferensi Mahasiswa TI 2024",
            kategori="penghargaan",
            deskripsi="Penghargaan paper terbaik di Konferensi Nasional Mahasiswa Teknik Informatika untuk topik penerapan machine learning di layanan kesehatan.",
            tahun=2024,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Aplikasi Mobile E-Health Tracker",
            kategori="karya",
            deskripsi="Membangun aplikasi mobile berbasis Flutter untuk membantu tracking kesehatan harian: gizi, aktivitas fisik, dan riwayat medis.",
            tahun=2024,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Web Portal KKN Mahasiswa UYP",
            kategori="karya",
            deskripsi="Pengembangan portal web internal untuk koordinasi program KKN antar prodi menggunakan Flask + PostgreSQL.",
            tahun=2025,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Sertifikasi AWS Cloud Practitioner",
            kategori="sertifikasi",
            deskripsi="Sertifikasi resmi Amazon Web Services untuk pemahaman dasar layanan cloud, keamanan, dan billing.",
            tahun=2024,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="TOEFL ITP — Score 567",
            kategori="sertifikasi",
            deskripsi="Sertifikat TOEFL ITP dengan skor 567 yang menunjukkan kemampuan bahasa Inggris menengah-lanjut.",
            tahun=2024,
        ),
        Portfolio(
            mahasiswa_id=mhs.id,
            judul="Volunteer Pengabdian Masyarakat 2024",
            kategori="lainnya",
            deskripsi="Anggota tim pengabdian masyarakat UYP di Desa Sukamulya: edukasi gizi & literasi digital untuk warga.",
            tahun=2024,
        ),
    ])

    db.session.commit()

    # ── Konten publik: Berita / Kegiatan / Kerja Sama ──────────────────
    _seed_konten_publik(admin_sosmed.id)


def _seed_konten_publik(admin_id: int) -> None:
    """Isi data demo Berita/Kegiatan/KerjaSama bila tabel masih kosong."""
    if Berita.query.count() == 0:
        now = datetime.utcnow()
        db.session.add_all([
            Berita(
                judul="Yarsi Pratama Buka Pendaftaran Mahasiswa Baru 2025/2026",
                ringkasan="Pendaftaran mahasiswa baru Universitas Yarsi Pratama untuk Tahun Akademik 2025/2026 resmi dibuka dengan kuota beasiswa hingga 100% UKT.",
                isi=(
                    "Universitas Yarsi Pratama (UYP) resmi membuka penerimaan mahasiswa baru "
                    "(PMB) Tahun Akademik 2025/2026 mulai bulan ini. Pendaftaran dapat dilakukan "
                    "secara online melalui website resmi kampus dengan biaya pendaftaran terjangkau.\n\n"
                    "Rektor UYP menyampaikan bahwa pada tahun ini kampus menyediakan kuota beasiswa "
                    "yang lebih luas, termasuk beasiswa akademik, tahfizh, dan KIP-Kuliah. "
                    "\"Kami ingin memastikan tidak ada anak bangsa yang terhalang biaya untuk meraih "
                    "pendidikan tinggi berkualitas,\" ujar beliau.\n\n"
                    "Calon mahasiswa dapat memilih dari 8 program studi unggulan di dua fakultas: "
                    "Fakultas Ilmu Kesehatan dan FTBH. Informasi selengkapnya tersedia di halaman PMB."
                ),
                kategori="Pengumuman", penulis_id=admin_id,
                published_at=now - timedelta(days=1), status="published",
            ),
            Berita(
                judul="Mahasiswa Teknik Informatika Raih Juara Hackathon Nasional",
                ringkasan="Tim mahasiswa Prodi Teknik Informatika UYP berhasil meraih juara 1 pada ajang Hackathon Nasional 2024.",
                isi=(
                    "Tim mahasiswa Prodi S1 Teknik Informatika Universitas Yarsi Pratama berhasil "
                    "menorehkan prestasi membanggakan dengan meraih juara 1 pada ajang Hackathon "
                    "Nasional 2024 yang diselenggarakan oleh Kementerian Kominfo.\n\n"
                    "Tim yang beranggotakan 4 mahasiswa angkatan 2022 ini berhasil mengalahkan "
                    "lebih dari 200 tim dari seluruh Indonesia dengan menciptakan aplikasi "
                    "berbasis AI untuk membantu UMKM dalam pengelolaan stok dan penjualan.\n\n"
                    "Prestasi ini merupakan bukti nyata kualitas pendidikan dan bimbingan dosen "
                    "praktisi yang ada di Yarsi Pratama. Selamat untuk para juara!"
                ),
                kategori="Prestasi", penulis_id=admin_id,
                published_at=now - timedelta(days=5), status="published",
            ),
            Berita(
                judul="Akreditasi Baik Sekali untuk Prodi S1 Manajemen",
                ringkasan="Program Studi S1 Manajemen UYP memperoleh peringkat akreditasi Baik Sekali dari LAMEMBA.",
                isi=(
                    "Program Studi S1 Manajemen Universitas Yarsi Pratama berhasil memperoleh "
                    "peringkat akreditasi Baik Sekali dari Lembaga Akreditasi Mandiri Ekonomi, "
                    "Manajemen, Bisnis, dan Akuntansi (LAMEMBA).\n\n"
                    "Pencapaian ini menjadi salah satu indikator kualitas penyelenggaraan "
                    "pendidikan di prodi yang telah berdiri sejak awal pendirian universitas. "
                    "Kurikulum berbasis kompetensi, dosen berkualitas, dan fasilitas pembelajaran "
                    "yang lengkap menjadi faktor pendukung pencapaian akreditasi ini."
                ),
                kategori="Akademik", penulis_id=admin_id,
                published_at=now - timedelta(days=10), status="published",
            ),
            Berita(
                judul="Kuliah Umum: Transformasi Digital di Sektor Kesehatan",
                ringkasan="Fakultas Ilmu Kesehatan menggelar kuliah umum dengan pembicara dari Kementerian Kesehatan RI.",
                isi=(
                    "Fakultas Ilmu Kesehatan Universitas Yarsi Pratama menyelenggarakan kuliah "
                    "umum bertajuk \"Transformasi Digital di Sektor Kesehatan: Peluang dan Tantangan\" "
                    "yang dihadiri lebih dari 300 mahasiswa.\n\n"
                    "Kegiatan yang berlangsung di Auditorium Kampus ini menghadirkan pembicara "
                    "dari Direktorat Jenderal Pelayanan Kesehatan Kementerian Kesehatan RI. "
                    "Para mahasiswa antusias mengikuti sesi tanya jawab dan diskusi interaktif "
                    "tentang implementasi rekam medis elektronik dan telemedicine."
                ),
                kategori="Akademik", penulis_id=admin_id,
                published_at=now - timedelta(days=14), status="published",
            ),
            Berita(
                judul="Kemitraan Strategis Yarsi Pratama dengan PT Telkom Indonesia",
                ringkasan="UYP menandatangani MoU strategis dengan PT Telkom Indonesia untuk program magang dan riset bersama.",
                isi=(
                    "Universitas Yarsi Pratama resmi menandatangani Memorandum of Understanding "
                    "(MoU) dengan PT Telkom Indonesia. Kerja sama strategis ini mencakup program "
                    "magang industri, riset bersama, dan rekrutmen mahasiswa berprestasi.\n\n"
                    "Dengan adanya MoU ini, mahasiswa UYP terutama dari Prodi Teknik Informatika "
                    "dan Ilmu Komunikasi memiliki akses lebih luas ke pengalaman industri nyata. "
                    "Program magang dimulai semester ganjil 2025."
                ),
                kategori="Kerjasama", penulis_id=admin_id,
                published_at=now - timedelta(days=20), status="published",
            ),
            Berita(
                judul="Pengabdian Masyarakat: Edukasi Gizi untuk Ibu Hamil",
                ringkasan="Mahasiswa Prodi Ilmu Gizi mengadakan program edukasi gizi seimbang bagi ibu hamil di Desa Sukamulya.",
                isi=(
                    "Sebagai bentuk pengabdian masyarakat, mahasiswa Prodi S1 Ilmu Gizi UYP "
                    "menyelenggarakan program edukasi gizi seimbang bagi ibu hamil di Desa "
                    "Sukamulya, Bogor.\n\n"
                    "Kegiatan ini melibatkan 30 mahasiswa yang dibagi dalam beberapa kelompok "
                    "untuk memberikan konsultasi gizi, pemeriksaan tekanan darah, dan demo masak "
                    "menu seimbang. Sekitar 80 ibu hamil dari desa tersebut berpartisipasi aktif."
                ),
                kategori="Pengabdian", penulis_id=admin_id,
                published_at=now - timedelta(days=28), status="published",
            ),
            # ── Pengumuman resmi (dilist di section khusus) ─────────────
            Berita(
                judul="Jadwal Ujian Tengah Semester (UTS) Ganjil 2025/2026",
                ringkasan="UTS akan dilaksanakan 28 Oktober – 8 November 2025. Cek jadwal di portal LMS.",
                isi=(
                    "Diberitahukan kepada seluruh mahasiswa aktif bahwa pelaksanaan Ujian "
                    "Tengah Semester (UTS) Ganjil Tahun Akademik 2025/2026 akan berlangsung "
                    "pada 28 Oktober s.d. 8 November 2025.\n\n"
                    "Jadwal lengkap setiap mata kuliah dapat dilihat di portal LMS, menu "
                    "Jadwal. Mahasiswa wajib hadir paling lambat 15 menit sebelum ujian dimulai "
                    "dan membawa Kartu Tanda Mahasiswa (KTM)."
                ),
                kategori="Pengumuman", penulis_id=admin_id,
                published_at=now - timedelta(days=2), status="published",
            ),
            Berita(
                judul="Beasiswa Prestasi Akademik Semester Genap Dibuka",
                ringkasan="Mahasiswa dengan IPK ≥ 3.50 dapat mengajukan beasiswa hingga 50% UKT.",
                isi=(
                    "Universitas Yarsi Pratama membuka pendaftaran Beasiswa Prestasi Akademik "
                    "untuk Semester Genap 2025/2026 bagi mahasiswa dengan IPK minimal 3.50 dan "
                    "aktif di kegiatan organisasi kampus.\n\n"
                    "Pendaftaran dibuka hingga 30 November 2025. Berkas yang diperlukan: "
                    "transkrip nilai, surat rekomendasi dosen wali, dan surat keterangan aktif "
                    "organisasi. Beasiswa berupa potongan UKT 25-50% sesuai kategori."
                ),
                kategori="Pengumuman", penulis_id=admin_id,
                published_at=now - timedelta(days=4), status="published",
            ),
            Berita(
                judul="Pengisian KRS Semester Genap 2025/2026",
                ringkasan="Periode pengisian KRS 5 - 12 Januari 2026. Konsultasi DW wajib.",
                isi=(
                    "Periode pengisian Kartu Rencana Studi (KRS) Semester Genap 2025/2026 "
                    "akan dibuka pada tanggal 5 - 12 Januari 2026.\n\n"
                    "Setiap mahasiswa wajib melakukan konsultasi dengan Dosen Wali masing-masing "
                    "sebelum melakukan input KRS di portal LMS. Konsultasi dapat dilakukan online "
                    "melalui fitur Konseling atau tatap muka sesuai jadwal masing-masing DW."
                ),
                kategori="Pengumuman", penulis_id=admin_id,
                published_at=now - timedelta(days=8), status="published",
            ),
            Berita(
                judul="Libur Hari Raya & Cuti Bersama Nasional",
                ringkasan="Perkuliahan dan pelayanan akademik diliburkan selama hari raya nasional.",
                isi=(
                    "Mengacu pada Surat Keputusan Bersama 3 Menteri tentang Hari Libur Nasional "
                    "dan Cuti Bersama, perkuliahan dan layanan akademik akan diliburkan "
                    "menyesuaikan tanggal yang ditetapkan pemerintah.\n\n"
                    "Mohon mahasiswa memperhatikan jadwal kuliah pengganti yang akan diumumkan "
                    "oleh masing-masing dosen pengampu melalui LMS. Layanan administrasi akan "
                    "kembali normal pada hari kerja berikutnya."
                ),
                kategori="Pengumuman", penulis_id=admin_id,
                published_at=now - timedelta(days=12), status="published",
            ),
        ])

    if Kegiatan.query.count() == 0:
        now = datetime.utcnow()
        db.session.add_all([
            Kegiatan(
                judul="Seminar Nasional Kesehatan Digital 2025",
                ringkasan="Seminar nasional yang mengangkat tema integrasi teknologi digital dalam pelayanan kesehatan modern.",
                isi=(
                    "Fakultas Ilmu Kesehatan UYP mengundang Anda pada Seminar Nasional Kesehatan "
                    "Digital 2025 dengan tema \"Integrasi AI dalam Pelayanan Kesehatan Modern\".\n\n"
                    "Acara ini menghadirkan pakar dari Kementerian Kesehatan, RSPI Sulianti Saroso, "
                    "dan praktisi kesehatan digital. Tersedia sertifikat ber-SKP IDI 4 SKP untuk "
                    "tenaga kesehatan. Pendaftaran gratis untuk mahasiswa UYP."
                ),
                lokasi="Auditorium Utama Kampus", penyelenggara="Fakultas Ilmu Kesehatan",
                tanggal_mulai=now + timedelta(days=14, hours=8),
                tanggal_selesai=now + timedelta(days=14, hours=16),
                penulis_id=admin_id, status="published",
            ),
            Kegiatan(
                judul="Workshop Web Development & Cloud Computing",
                ringkasan="Workshop intensif 2 hari untuk mahasiswa TI seputar pengembangan web modern dan cloud computing.",
                isi=(
                    "HMTI bekerja sama dengan Prodi Teknik Informatika mengadakan workshop "
                    "intensif selama 2 hari penuh tentang Web Development dan Cloud Computing.\n\n"
                    "Materi workshop meliputi: React.js, Node.js, Docker, AWS, dan deployment "
                    "production-ready application. Peserta akan mengerjakan proyek nyata "
                    "yang dapat dimasukkan dalam portofolio. Disediakan voucher AWS senilai $50 "
                    "untuk seluruh peserta."
                ),
                lokasi="Lab Komputer 2 & 3", penyelenggara="HMTI Yarsi Pratama",
                tanggal_mulai=now + timedelta(days=7, hours=9),
                tanggal_selesai=now + timedelta(days=8, hours=17),
                penulis_id=admin_id, status="published",
            ),
            Kegiatan(
                judul="Open House & Campus Tour PMB 2025",
                ringkasan="Acara open house untuk calon mahasiswa baru, dengan campus tour, talkshow, dan testing aptitude.",
                isi=(
                    "Calon mahasiswa baru? Jangan lewatkan Open House & Campus Tour Universitas "
                    "Yarsi Pratama yang akan diadakan setiap akhir pekan selama bulan promosi.\n\n"
                    "Agenda: Campus tour, talkshow dengan alumni sukses, mini-aptitude test "
                    "gratis untuk menentukan minat dan bakat, sesi tanya jawab dengan ketua "
                    "prodi, dan diskon pendaftaran 50% untuk yang mendaftar di hari yang sama."
                ),
                lokasi="Seluruh Kampus", penyelenggara="Panitia PMB UYP",
                tanggal_mulai=now + timedelta(days=21, hours=8),
                tanggal_selesai=now + timedelta(days=21, hours=15),
                penulis_id=admin_id, status="published",
            ),
            Kegiatan(
                judul="Festival Seni & Budaya Mahasiswa UYP",
                ringkasan="Festival seni dan budaya yang menampilkan kreativitas mahasiswa UYP dari berbagai daerah.",
                isi=(
                    "BEM UYP mempersembahkan Festival Seni & Budaya Mahasiswa yang menampilkan "
                    "berbagai pertunjukan seni daerah, musik akustik, fashion show kostum "
                    "tradisional, dan pameran kuliner nusantara.\n\n"
                    "Acara dimeriahkan oleh penampilan tamu dari band lokal terkenal dan "
                    "kompetisi tarian tradisional antar-fakultas dengan total hadiah jutaan rupiah."
                ),
                lokasi="Lapangan Utama Kampus", penyelenggara="BEM Universitas",
                tanggal_mulai=now - timedelta(days=10, hours=-13),
                tanggal_selesai=now - timedelta(days=10, hours=-22),
                penulis_id=admin_id, status="published",
            ),
            Kegiatan(
                judul="Yudisium dan Wisuda XII Yarsi Pratama",
                ringkasan="Acara yudisium dan wisuda angkatan ke-12 yang mewisuda 350 mahasiswa dari berbagai program studi.",
                isi=(
                    "Universitas Yarsi Pratama mengadakan upacara yudisium dan wisuda angkatan "
                    "ke-12 yang akan mewisuda 350 mahasiswa dari berbagai program studi.\n\n"
                    "Acara akan dihadiri oleh keluarga wisudawan, pejabat Yayasan, dan tamu "
                    "undangan kehormatan. Sesi inspirational speech akan diberikan oleh alumni "
                    "berprestasi yang kini menjabat di posisi strategis di berbagai institusi."
                ),
                lokasi="Convention Hall Sentul",
                penyelenggara="Universitas Yarsi Pratama",
                tanggal_mulai=now + timedelta(days=45, hours=9),
                tanggal_selesai=now + timedelta(days=45, hours=14),
                penulis_id=admin_id, status="published",
            ),
        ])

    if KerjaSama.query.count() == 0:
        today = datetime.utcnow().date()
        db.session.add_all([
            KerjaSama(
                judul="Program Magang & Riset Bersama PT Telkom Indonesia",
                mitra="PT Telkom Indonesia (Persero) Tbk",
                ringkasan="Kerja sama strategis di bidang magang, riset, dan rekrutmen mahasiswa terbaik UYP.",
                isi=(
                    "Kerja sama strategis antara Universitas Yarsi Pratama dengan PT Telkom "
                    "Indonesia mencakup program magang mahasiswa Prodi TI, riset bersama di "
                    "bidang telekomunikasi digital, dan jalur fast-track rekrutmen untuk "
                    "lulusan berprestasi UYP.\n\n"
                    "Program magang dilaksanakan setiap semester dengan total kuota 20 mahasiswa "
                    "per angkatan dan kompensasi yang layak."
                ),
                kategori="Industri", tanggal_mou=today - timedelta(days=60),
                masa_berlaku="5 tahun (2025–2030)", penulis_id=admin_id, status="published",
            ),
            KerjaSama(
                judul="Pendidikan Kebidanan Klinis RSUD Bogor",
                mitra="RSUD Kota Bogor",
                ringkasan="Kerja sama praktik klinis kebidanan dan studi kasus nyata untuk mahasiswa D3 Kebidanan.",
                isi=(
                    "Mahasiswa D3 Kebidanan UYP melaksanakan praktik klinis di RSUD Kota Bogor "
                    "dengan supervisi langsung dari bidan senior dan dokter spesialis. "
                    "Kerja sama ini memberikan pengalaman langsung pada layanan poli kebidanan, "
                    "ruang bersalin, dan kunjungan rumah pasien.\n\n"
                    "RSUD juga menjadi tempat penelitian dan studi kasus untuk skripsi mahasiswa."
                ),
                kategori="Pemerintah", tanggal_mou=today - timedelta(days=180),
                masa_berlaku="3 tahun (2024–2027)", penulis_id=admin_id, status="published",
            ),
            KerjaSama(
                judul="Pertukaran Akademik dengan Universitas Malaya",
                mitra="Universiti Malaya (Malaysia)",
                ringkasan="Program pertukaran mahasiswa dan dosen serta riset kolaboratif tingkat internasional.",
                isi=(
                    "UYP menjalin kerja sama internasional dengan Universiti Malaya melalui "
                    "program student exchange, joint research, dan double-degree untuk program "
                    "S1 Manajemen dan S1 Hukum.\n\n"
                    "Setiap tahun tersedia 5 kuota mahasiswa UYP untuk mengikuti semester di "
                    "Malaysia dengan beasiswa parsial dari kedua universitas."
                ),
                kategori="Internasional", tanggal_mou=today - timedelta(days=400),
                masa_berlaku="5 tahun", penulis_id=admin_id, status="published",
            ),
            KerjaSama(
                judul="Inkubator Bisnis Mahasiswa dengan Bank BRI",
                mitra="PT Bank Rakyat Indonesia (Persero) Tbk",
                ringkasan="Pendampingan inkubator bisnis dan akses pembiayaan untuk start-up mahasiswa UYP.",
                isi=(
                    "Mahasiswa UYP yang memiliki ide bisnis mendapatkan pendampingan langsung "
                    "dari mentor BRI Inkubator. Program mencakup pelatihan business model "
                    "canvas, pitching, dan akses pembiayaan modal usaha mahasiswa.\n\n"
                    "Setiap tahun 10 ide bisnis terbaik mendapatkan pendanaan awal hingga "
                    "Rp 25 juta per tim."
                ),
                kategori="Industri", tanggal_mou=today - timedelta(days=120),
                masa_berlaku="2 tahun", penulis_id=admin_id, status="published",
            ),
            KerjaSama(
                judul="Pemerintah Kota Bogor: Pengabdian Masyarakat",
                mitra="Pemerintah Kota Bogor",
                ringkasan="Program pengabdian masyarakat KKN tematik untuk pengembangan desa di wilayah Kota Bogor.",
                isi=(
                    "Universitas Yarsi Pratama dan Pemkot Bogor bersinergi melaksanakan program "
                    "KKN tematik di 15 kelurahan. Mahasiswa dari berbagai prodi berkontribusi "
                    "sesuai kompetensi: TI untuk digitalisasi UMKM, Kebidanan untuk posyandu, "
                    "Manajemen untuk koperasi, Hukum untuk legalisasi usaha, dan Komunikasi "
                    "untuk branding desa."
                ),
                kategori="Pemerintah", tanggal_mou=today - timedelta(days=200),
                masa_berlaku="4 tahun (2024–2028)", penulis_id=admin_id, status="published",
            ),
            KerjaSama(
                judul="Riset Sertifikasi Halal dengan MUI Jawa Barat",
                mitra="Majelis Ulama Indonesia (MUI) Jawa Barat",
                ringkasan="Kerja sama riset dan sertifikasi halal untuk produk UMKM mahasiswa serta pelatihan auditor halal.",
                isi=(
                    "Prodi Ilmu Gizi dan Manajemen UYP bekerja sama dengan MUI Jawa Barat "
                    "dalam riset standar halal pangan dan pendampingan UMKM mahasiswa untuk "
                    "memperoleh sertifikasi halal.\n\n"
                    "Mahasiswa juga mendapatkan kesempatan mengikuti pelatihan auditor halal "
                    "bersertifikat MUI dengan biaya yang disubsidi."
                ),
                kategori="Akademik", tanggal_mou=today - timedelta(days=90),
                masa_berlaku="3 tahun", penulis_id=admin_id, status="published",
            ),
        ])

    db.session.commit()
