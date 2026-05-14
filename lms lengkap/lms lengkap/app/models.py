"""
app/models.py
=============
Seluruh model SQLAlchemy untuk LMS Universitas Yarsi Pratama.

Konvensi penamaan:
- Tabel pakai snake_case (tugas, absen, dst.).
- Foreign key pakai pola ``<tabel>_id``.
- Timestamp default UTC.

Hubungan utama:
    User (role: mahasiswa/dosen/admin/super_admin)
        |- ProfilMahasiswa (1-1) -> ProgramStudi
        |- ProfilDosen     (1-1) <-> ProgramStudi (M-M, via dosen_prodi)
    ProgramStudi -> MataKuliah -> Kelas -> Jadwal
    Kelas <-> User (mahasiswa) via krs_kelas
    Kelas -> Tugas -> Jawaban (dari mahasiswa)
    Kelas -> Absen (per pertemuan, per mahasiswa)
    Kelas -> Nilai (komponen Kuis/Tugas/UTS/UAS/Keaktifan/Proyek)
    Mahasiswa -> Poin (ke dosen, max 10/semester)
    Mahasiswa <-> Dosen via Konseling (chat thread + pesan)
"""
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db


# =====================================================================
# SETTINGS - kunci/nilai konfigurasi runtime (KRS dibuka, nilai dibuka,
# system locked, dsb.).
# =====================================================================
class SystemSetting(db.Model):
    __tablename__ = "system_setting"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), nullable=True)

    @classmethod
    def get(cls, key: str, default: str | None = None):
        row = cls.query.get(key)
        return row.value if row else default

    @classmethod
    def set(cls, key: str, value: str):
        row = cls.query.get(key)
        if row:
            row.value = value
        else:
            row = cls(key=key, value=value)
            db.session.add(row)
        db.session.commit()


# =====================================================================
# USER + PROFIL
# =====================================================================
class User(db.Model, UserMixin):
    """Tabel utama untuk semua role."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(
        db.String(20), nullable=False, default="mahasiswa"
    )  # mahasiswa | dosen | admin | admin_sosmed | superadmin
    status = db.Column(
        db.String(20), nullable=False, default="pending"
    )  # pending | aktif | nonaktif | ditolak

    email_verified = db.Column(db.Boolean, default=False, nullable=False)

    foto = db.Column(db.String(255), nullable=True)
    no_telp = db.Column(db.String(30), nullable=True)
    alamat = db.Column(db.String(255), nullable=True)
    tanggal_lahir = db.Column(db.Date, nullable=True)
    jenis_kelamin = db.Column(db.String(10), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    # Relasi
    profil_mahasiswa = db.relationship(
        "ProfilMahasiswa", uselist=False, back_populates="user", cascade="all, delete-orphan"
    )
    profil_dosen = db.relationship(
        "ProfilDosen", uselist=False, back_populates="user", cascade="all, delete-orphan"
    )

    # ---- helpers ----
    def set_password(self, raw: str) -> None:
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw: str) -> bool:
        return check_password_hash(self.password_hash, raw)

    @property
    def is_active(self) -> bool:  # dipakai Flask-Login
        return self.status == "aktif"

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email} {self.role}>"


class ProgramStudi(db.Model):
    __tablename__ = "program_studi"
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(120), unique=True, nullable=False)
    fakultas = db.Column(db.String(120), nullable=False)
    deskripsi = db.Column(db.Text, nullable=True)


class ProfilMahasiswa(db.Model):
    __tablename__ = "profil_mahasiswa"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    nim = db.Column(db.String(30), unique=True, nullable=False)
    prodi_id = db.Column(db.Integer, db.ForeignKey("program_studi.id"), nullable=False)
    angkatan = db.Column(db.Integer, nullable=False, default=2024)
    semester = db.Column(db.Integer, nullable=False, default=1)
    ipk = db.Column(db.Float, nullable=True)
    organisasi = db.Column(db.Text, nullable=True)  # diisi admin
    jenis_kelas = db.Column(
        db.String(20), nullable=False, default="reguler"
    )  # reguler | nonreguler

    user = db.relationship("User", back_populates="profil_mahasiswa")
    prodi = db.relationship("ProgramStudi")


# tabel pivot dosen <-> prodi (max 10 prodi per dosen, dijaga di route)
dosen_prodi = db.Table(
    "dosen_prodi",
    db.Column("dosen_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
    db.Column("prodi_id", db.Integer, db.ForeignKey("program_studi.id"), primary_key=True),
)


class ProfilDosen(db.Model):
    __tablename__ = "profil_dosen"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    nidn = db.Column(db.String(30), unique=True, nullable=False)
    jabatan = db.Column(db.String(80), nullable=True)
    riwayat_akademik = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="profil_dosen")
    prodi_list = db.relationship(
        "ProgramStudi",
        secondary=dosen_prodi,
        primaryjoin="ProfilDosen.user_id==dosen_prodi.c.dosen_id",
        secondaryjoin="ProgramStudi.id==dosen_prodi.c.prodi_id",
        backref="dosen_pengajar",
    )


# =====================================================================
# VERIFIKASI EMAIL & RESET PASSWORD
# =====================================================================
class EmailVerification(db.Model):
    """Kode 6 digit yang dikirim via SMTP saat pendaftaran/lupa password."""

    __tablename__ = "email_verification"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    code = db.Column(db.String(10), nullable=False)
    purpose = db.Column(db.String(20), nullable=False, default="register")  # register|reset
    used = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)


# =====================================================================
# MASTER MATA KULIAH & KELAS PARALEL
# =====================================================================
class MataKuliah(db.Model):
    __tablename__ = "mata_kuliah"
    id = db.Column(db.Integer, primary_key=True)
    kode = db.Column(db.String(20), unique=True, nullable=False)
    nama = db.Column(db.String(120), nullable=False)
    rumpun = db.Column(db.String(80), nullable=True)
    sks = db.Column(db.Integer, nullable=False, default=3)
    jenis = db.Column(db.String(20), nullable=False, default="wajib")  # wajib|pilihan
    prasyarat_id = db.Column(db.Integer, db.ForeignKey("mata_kuliah.id"), nullable=True)
    silabus = db.Column(db.String(255), nullable=True)  # path file
    prodi_id = db.Column(db.Integer, db.ForeignKey("program_studi.id"), nullable=False)
    semester = db.Column(db.Integer, nullable=False, default=1)

    prodi = db.relationship("ProgramStudi")
    prasyarat = db.relationship("MataKuliah", remote_side=[id])


class Kelas(db.Model):
    """Kelas paralel dari satu mata kuliah (A/B/C, dst.) + dosen pengampu."""

    __tablename__ = "kelas"
    id = db.Column(db.Integer, primary_key=True)
    matkul_id = db.Column(db.Integer, db.ForeignKey("mata_kuliah.id"), nullable=False)
    dosen_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kode_kelas = db.Column(db.String(10), nullable=False, default="A")
    kuota = db.Column(db.Integer, nullable=False, default=40)
    semester_aktif = db.Column(db.Integer, nullable=False, default=1)
    tahun_ajaran = db.Column(db.String(20), nullable=False, default="2024/2025-Ganjil")
    jenis_kelas = db.Column(
        db.String(20), nullable=False, default="reguler"
    )  # reguler | nonreguler

    matkul = db.relationship("MataKuliah")
    dosen = db.relationship("User", foreign_keys=[dosen_id])

    @property
    def label(self) -> str:
        jk = "NR" if self.jenis_kelas == "nonreguler" else "R"
        return f"{self.matkul.kode}-{self.kode_kelas} ({jk})"


class Jadwal(db.Model):
    __tablename__ = "jadwal"
    id = db.Column(db.Integer, primary_key=True)
    kelas_id = db.Column(db.Integer, db.ForeignKey("kelas.id"), nullable=False)
    hari = db.Column(db.String(10), nullable=False)  # Senin..Minggu
    jam_mulai = db.Column(db.String(5), nullable=False)  # "08:00"
    jam_selesai = db.Column(db.String(5), nullable=False)  # "10:30"
    ruangan = db.Column(db.String(40), nullable=False)

    kelas = db.relationship("Kelas", backref="jadwal_list")


# =====================================================================
# KRS (pengisian mata kuliah oleh mahasiswa)
# =====================================================================
class KRS(db.Model):
    """Pivot mahasiswa <-> kelas yang diambil pada semester berjalan."""

    __tablename__ = "krs"
    id = db.Column(db.Integer, primary_key=True)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    kelas_id = db.Column(db.Integer, db.ForeignKey("kelas.id"), nullable=False)
    semester = db.Column(db.Integer, nullable=False, default=1)
    tahun_ajaran = db.Column(db.String(20), nullable=False, default="2024/2025-Ganjil")
    status = db.Column(db.String(20), default="aktif")  # aktif|dibatalkan
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    mahasiswa = db.relationship("User", foreign_keys=[mahasiswa_id])
    kelas = db.relationship("Kelas")

    __table_args__ = (
        db.UniqueConstraint("mahasiswa_id", "kelas_id", "tahun_ajaran", name="uq_krs"),
    )


# =====================================================================
# TUGAS & JAWABAN
# =====================================================================
class Tugas(db.Model):
    __tablename__ = "tugas"
    id = db.Column(db.Integer, primary_key=True)
    kelas_id = db.Column(db.Integer, db.ForeignKey("kelas.id"), nullable=False)
    judul = db.Column(db.String(160), nullable=False)
    deskripsi = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(255), nullable=True)  # file dari dosen (opsional)
    deadline = db.Column(db.DateTime, nullable=True)
    jenis = db.Column(db.String(20), default="tugas")  # kuis|tugas|uts|uas|proyek
    bobot = db.Column(db.Integer, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    kelas = db.relationship("Kelas")


class JawabanTugas(db.Model):
    __tablename__ = "jawaban_tugas"
    id = db.Column(db.Integer, primary_key=True)
    tugas_id = db.Column(db.Integer, db.ForeignKey("tugas.id"), nullable=False)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    teks = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    nilai = db.Column(db.Float, nullable=True)
    feedback = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    tugas = db.relationship("Tugas")
    mahasiswa = db.relationship("User")


# =====================================================================
# ABSENSI
# =====================================================================
class Absen(db.Model):
    __tablename__ = "absen"
    id = db.Column(db.Integer, primary_key=True)
    kelas_id = db.Column(db.Integer, db.ForeignKey("kelas.id"), nullable=False)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    pertemuan_ke = db.Column(db.Integer, nullable=False, default=1)
    tanggal = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    status = db.Column(db.String(10), nullable=False, default="hadir")  # hadir|izin|alpha|sakit
    alasan = db.Column(db.String(255), nullable=True)

    kelas = db.relationship("Kelas")
    mahasiswa = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("kelas_id", "mahasiswa_id", "pertemuan_ke", name="uq_absen"),
    )


# =====================================================================
# MATERI (konten belajar per kelas, mendukung link YouTube)
# =====================================================================
class Materi(db.Model):
    """Materi pembelajaran per kelas. Mendukung link video YouTube
    yang otomatis di-embed dan ditampilkan thumbnail-nya."""

    __tablename__ = "materi"
    id = db.Column(db.Integer, primary_key=True)
    kelas_id = db.Column(db.Integer, db.ForeignKey("kelas.id"), nullable=False)
    judul = db.Column(db.String(200), nullable=False)
    deskripsi = db.Column(db.Text, nullable=True)
    youtube_url = db.Column(db.String(500), nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    urutan = db.Column(db.Integer, nullable=False, default=1)
    semester = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    kelas = db.relationship("Kelas", backref="materi_list")

    @property
    def youtube_video_id(self) -> str | None:
        """Ekstrak video ID dari berbagai format URL YouTube."""
        import re
        if not self.youtube_url:
            return None
        patterns = [
            r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com/v/([a-zA-Z0-9_-]{11})',
        ]
        for p in patterns:
            m = re.search(p, self.youtube_url)
            if m:
                return m.group(1)
        return None

    @property
    def youtube_thumbnail(self) -> str | None:
        """URL thumbnail YouTube (resolusi max)."""
        vid = self.youtube_video_id
        return f"https://img.youtube.com/vi/{vid}/hqdefault.jpg" if vid else None


# =====================================================================
# PORTFOLIO (prestasi/karya mahasiswa, dikelola admin)
# =====================================================================
class Portfolio(db.Model):
    """Data prestasi/karya mahasiswa yang diinput oleh Admin.
    Mahasiswa dan Dosen hanya boleh melihat (View).
    Admin memiliki Full Access (CRUD)."""

    __tablename__ = "portfolio"
    id = db.Column(db.Integer, primary_key=True)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    judul = db.Column(db.String(200), nullable=False)
    kategori = db.Column(db.String(80), nullable=True)  # prestasi|karya|sertifikasi|lainnya
    deskripsi = db.Column(db.Text, nullable=True)
    tahun = db.Column(db.Integer, nullable=True)
    bukti_path = db.Column(db.String(255), nullable=True)  # file bukti (opsional)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    mahasiswa = db.relationship("User", backref="portfolio_list")


# =====================================================================
# NILAI (rekap final per kelas, dari komponen)
# =====================================================================
class Nilai(db.Model):
    __tablename__ = "nilai"
    id = db.Column(db.Integer, primary_key=True)
    kelas_id = db.Column(db.Integer, db.ForeignKey("kelas.id"), nullable=False)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    semester = db.Column(db.Integer, nullable=False, default=1)
    nilai_kuis = db.Column(db.Float, default=0)
    nilai_tugas = db.Column(db.Float, default=0)
    nilai_uts = db.Column(db.Float, default=0)
    nilai_uas = db.Column(db.Float, default=0)
    nilai_keaktifan = db.Column(db.Float, default=0)
    nilai_proyek = db.Column(db.Float, default=0)
    nilai_akhir = db.Column(db.Float, default=0)
    grade = db.Column(db.String(2), default="-")
    catatan = db.Column(db.Text, nullable=True)

    kelas = db.relationship("Kelas")
    mahasiswa = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("kelas_id", "mahasiswa_id", "semester", name="uq_nilai"),
    )

    def hitung(self):
        """Hitung nilai akhir berbobot Kuis 5% Tugas 10% UTS 15% UAS 20%
        Keaktifan 20% Proyek 30%. Total = 100%."""
        akhir = (
            (self.nilai_kuis or 0) * 0.05
            + (self.nilai_tugas or 0) * 0.10
            + (self.nilai_uts or 0) * 0.15
            + (self.nilai_uas or 0) * 0.20
            + (self.nilai_keaktifan or 0) * 0.20
            + (self.nilai_proyek or 0) * 0.30
        )
        self.nilai_akhir = round(akhir, 2)
        # konversi sederhana ke huruf
        if akhir >= 85:
            self.grade = "A"
        elif akhir >= 75:
            self.grade = "B"
        elif akhir >= 65:
            self.grade = "C"
        elif akhir >= 55:
            self.grade = "D"
        else:
            self.grade = "E"


# =====================================================================
# POIN MAHASISWA -> DOSEN (max 10 / semester)
# =====================================================================
class Poin(db.Model):
    __tablename__ = "poin"
    id = db.Column(db.Integer, primary_key=True)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    dosen_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    nilai_poin = db.Column(db.Integer, nullable=False, default=0)
    semester = db.Column(db.Integer, nullable=False, default=1)
    tahun_ajaran = db.Column(db.String(20), nullable=False, default="2024/2025-Ganjil")
    catatan = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    mahasiswa = db.relationship("User", foreign_keys=[mahasiswa_id])
    dosen = db.relationship("User", foreign_keys=[dosen_id])


# =====================================================================
# KONSELING (chat)
# =====================================================================
class KonselingThread(db.Model):
    """Tiket konseling mahasiswa <-> dosen.

    Workflow:
    - mahasiswa/dosen membuka tiket -> status=pending
    - dosen ACC -> status=active + accepted_at terisi, chat aktif
    - dosen (atau mahasiswa) mengakhiri tiket -> status=ended +
      ended_at terisi. Seluruh riwayat chat tetap tersimpan, tetapi
      tidak bisa ada pesan baru.
    - Setiap pihak punya tombol ``hapus riwayat`` yang HANYA
      menyembunyikan tiket tsb di sisinya sendiri (set
      ``deleted_by_mhs`` atau ``deleted_by_dosen`` = True). Pihak
      lain tetap dapat melihat & menyimpan riwayatnya.
    """
    __tablename__ = "konseling_thread"
    id = db.Column(db.Integer, primary_key=True)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    dosen_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    topik = db.Column(db.String(160), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="pending")
    opened_by = db.Column(db.String(16), nullable=True)  # "mahasiswa" | "dosen"
    accepted_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    ended_by = db.Column(db.String(16), nullable=True)
    deleted_by_mhs = db.Column(db.Boolean, default=False, nullable=False)
    deleted_by_dosen = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_message_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    mahasiswa = db.relationship("User", foreign_keys=[mahasiswa_id])
    dosen = db.relationship("User", foreign_keys=[dosen_id])

    # NB: sengaja TIDAK memakai UniqueConstraint (mahasiswa_id, dosen_id).
    # Setelah sebuah tiket diakhiri, kedua pihak dapat membuka tiket baru
    # lagi — riwayat lama harus tetap terpisah (tidak dicampur ke thread
    # yang sama).

    def is_visible_to(self, user) -> bool:
        if user.id == self.mahasiswa_id:
            return not self.deleted_by_mhs
        if user.id == self.dosen_id:
            return not self.deleted_by_dosen
        return False

    def can_chat(self) -> bool:
        return self.status == "active"


class KonselingPesan(db.Model):
    __tablename__ = "konseling_pesan"
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("konseling_thread.id"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    isi = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    thread = db.relationship("KonselingThread", backref="pesan_list")
    sender = db.relationship("User")


# =====================================================================
# PEMBAYARAN (UKT / SPP)
# =====================================================================
class Pembayaran(db.Model):
    __tablename__ = "pembayaran"
    id = db.Column(db.Integer, primary_key=True)
    mahasiswa_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    judul = db.Column(db.String(120), nullable=False, default="UKT Semester")
    nominal = db.Column(db.Integer, nullable=False, default=0)
    semester = db.Column(db.Integer, nullable=False, default=1)
    tahun_ajaran = db.Column(db.String(20), nullable=False, default="2024/2025-Ganjil")
    status = db.Column(db.String(20), default="belum_bayar")  # belum_bayar|menunggu|lunas|ditolak
    bukti = db.Column(db.String(255), nullable=True)
    catatan = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)

    mahasiswa = db.relationship("User")


# =====================================================================
# NOTIFIKASI
# =====================================================================
class Notifikasi(db.Model):
    __tablename__ = "notifikasi"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    judul = db.Column(db.String(160), nullable=False)
    isi = db.Column(db.Text, nullable=False)
    dibaca = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")


# =====================================================================
# AUDIT LOG (siapa mengubah apa)
# =====================================================================
class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    aksi = db.Column(db.String(80), nullable=False)
    target = db.Column(db.String(120), nullable=True)
    detail = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")


# =====================================================================
# AKTIVITAS LOGIN (statistik real-time admin)
# =====================================================================
class LoginActivity(db.Model):
    __tablename__ = "login_activity"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    prodi_id = db.Column(db.Integer, db.ForeignKey("program_studi.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =====================================================================
# KONTEN PUBLIK (Berita, Kegiatan, Kerja Sama)
# =====================================================================
class Berita(db.Model):
    """Berita kampus untuk halaman publik."""

    __tablename__ = "berita"
    id = db.Column(db.Integer, primary_key=True)
    judul = db.Column(db.String(200), nullable=False)
    ringkasan = db.Column(db.String(300), nullable=True)
    isi = db.Column(db.Text, nullable=False)
    gambar = db.Column(db.String(255), nullable=True)
    kategori = db.Column(db.String(60), nullable=True, default="Umum")
    penulis_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    published_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(20), default="published")  # published | draft
    views = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    penulis = db.relationship("User", foreign_keys=[penulis_id])


class Kegiatan(db.Model):
    """Kegiatan / event kampus."""

    __tablename__ = "kegiatan"
    id = db.Column(db.Integer, primary_key=True)
    judul = db.Column(db.String(200), nullable=False)
    ringkasan = db.Column(db.String(300), nullable=True)
    isi = db.Column(db.Text, nullable=False)
    gambar = db.Column(db.String(255), nullable=True)
    lokasi = db.Column(db.String(200), nullable=True)
    tanggal_mulai = db.Column(db.DateTime, nullable=True)
    tanggal_selesai = db.Column(db.DateTime, nullable=True)
    penyelenggara = db.Column(db.String(120), nullable=True)
    penulis_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String(20), default="published")
    views = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    penulis = db.relationship("User", foreign_keys=[penulis_id])


class KerjaSama(db.Model):
    """Mitra kerja sama kampus (MoU / industri / pemerintah)."""

    __tablename__ = "kerjasama"
    id = db.Column(db.Integer, primary_key=True)
    judul = db.Column(db.String(200), nullable=False)
    mitra = db.Column(db.String(160), nullable=False)
    ringkasan = db.Column(db.String(300), nullable=True)
    isi = db.Column(db.Text, nullable=False)
    logo = db.Column(db.String(255), nullable=True)  # logo mitra / banner
    kategori = db.Column(db.String(60), nullable=True, default="Industri")
    tanggal_mou = db.Column(db.Date, nullable=True)
    masa_berlaku = db.Column(db.String(60), nullable=True)
    penulis_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    status = db.Column(db.String(20), default="published")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    penulis = db.relationship("User", foreign_keys=[penulis_id])


class PendaftaranPMB(db.Model):
    """Form pendaftar PMB (lead) — tidak otomatis membuat akun.

    Digunakan untuk menampung pendaftar PMB dari halaman publik supaya
    admin dapat melakukan follow-up sebelum akun mahasiswa dibuat resmi.
    """

    __tablename__ = "pendaftaran_pmb"
    id = db.Column(db.Integer, primary_key=True)
    nama_lengkap = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160), nullable=False, index=True)
    no_telp = db.Column(db.String(30), nullable=False)
    asal_sekolah = db.Column(db.String(160), nullable=True)
    prodi_id = db.Column(db.Integer, db.ForeignKey("program_studi.id"), nullable=False)
    jalur = db.Column(db.String(60), nullable=True, default="Reguler")
    catatan = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default="baru")  # baru | diproses | diterima | ditolak
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    prodi = db.relationship("ProgramStudi")


# =====================================================================
# SKPI - Surat Keterangan Pendamping Ijazah
# Mahasiswa upload sertifikat (workshop/lomba/seminar/dll), admin
# mereview lalu memberi poin SKPI 1-4. Akumulasi poin tampil di profil
# mahasiswa dan ikut menjadi faktor ranking di leaderboard "Top Mahasiswa".
# =====================================================================
class SkpiPengajuan(db.Model):
    __tablename__ = "skpi_pengajuan"

    id = db.Column(db.Integer, primary_key=True)
    mahasiswa_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    judul = db.Column(db.String(200), nullable=False)
    kategori = db.Column(
        db.String(80), nullable=True
    )  # workshop|lomba|seminar|sertifikasi|pengabdian|lainnya
    deskripsi = db.Column(db.Text, nullable=True)
    tahun = db.Column(db.Integer, nullable=True)
    file_path = db.Column(db.String(255), nullable=False)  # path file sertifikat

    status = db.Column(
        db.String(20), nullable=False, default="pending", index=True
    )  # pending | approved | rejected
    poin = db.Column(db.Integer, nullable=True)  # 1..4, diisi admin saat approve
    catatan_admin = db.Column(db.Text, nullable=True)  # alasan reject / catatan

    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    mahasiswa = db.relationship(
        "User", foreign_keys=[mahasiswa_id], backref="skpi_pengajuan"
    )
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])
