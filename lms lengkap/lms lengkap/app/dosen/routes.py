"""
app/dosen/routes.py
===================
Halaman & API untuk role dosen.

Fitur:
- Dashboard ringkas.
- Daftar prodi yang diajar (read-only, di-assign admin atau dipilih saat register).
- Manajemen kelas yang diampu (lihat saja - admin yang plot).
- Tugas: buat tugas (dengan file 20 MB max), lihat jawaban mahasiswa, beri nilai+feedback.
- Absensi: pilih kelas + pertemuan -> tampilkan list mahasiswa dengan checkbox
  hadir/izin/alpha/sakit + kolom alasan; rekap per semester.
- Konseling: balas chat dari mahasiswa, atau mulai chat ke mahasiswa yang ada
  di kelas yang diampu (tidak bisa cross-prodi).
- Profil mahasiswa di kelasnya.
- Profil dosen (edit).
"""
from datetime import datetime, date

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
    current_app,
)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import (
    User, ProgramStudi, ProfilDosen, ProfilMahasiswa,
    MataKuliah, Kelas, Jadwal, KRS, Tugas, JawabanTugas,
    Absen, Nilai, Poin, KonselingThread, KonselingPesan,
    Materi,
)
from app.utils import save_upload

bp = Blueprint("dosen", __name__)


@bp.before_request
@login_required
def _require_dosen():
    if current_user.role != "dosen" or current_user.status != "aktif":
        abort(403)


def _kelas_diampu_ids():
    return [k.id for k in Kelas.query.filter_by(dosen_id=current_user.id).all()]


# ---------------------------------------------------------------------
@bp.route("/")
@bp.route("/dashboard")
def dashboard():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    total_mhs = (
        KRS.query.filter(
            KRS.kelas_id.in_([k.id for k in kelas_list]),
            KRS.status == "aktif",
        ).count() if kelas_list else 0
    )
    tugas_count = Tugas.query.filter(
        Tugas.kelas_id.in_([k.id for k in kelas_list])
    ).count() if kelas_list else 0
    jawaban_belum_dinilai = JawabanTugas.query.join(Tugas).filter(
        Tugas.kelas_id.in_([k.id for k in kelas_list]),
        JawabanTugas.nilai.is_(None),
    ).count() if kelas_list else 0

    poin_diterima = (
        db.session.query(db.func.sum(Poin.nilai_poin))
        .filter(Poin.dosen_id == current_user.id).scalar() or 0
    )
    return render_template(
        "dosen/dashboard.html", kelas_list=kelas_list, total_mhs=total_mhs,
        tugas_count=tugas_count, jawaban_belum_dinilai=jawaban_belum_dinilai,
        poin_diterima=poin_diterima,
    )


# ---------------------------------------------------------------------
@bp.route("/matkul")
def matkul():
    """Kelas / matkul yang diampu dosen."""
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    return render_template("dosen/dashboard.html", kelas_list=kelas_list, view="matkul")


# ---------------------------------------------------------------------
# TUGAS
# ---------------------------------------------------------------------
@bp.route("/tugas")
def tugas_list():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    tugas = Tugas.query.filter(
        Tugas.kelas_id.in_([k.id for k in kelas_list])
    ).order_by(Tugas.created_at.desc()).all() if kelas_list else []
    return render_template("dosen/tugas.html", tugas=tugas, kelas_list=kelas_list)


@bp.route("/tugas/baru", methods=["GET", "POST"])
def tugas_baru():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    if request.method == "POST":
        kelas_id = request.form.get("kelas_id", type=int)
        if kelas_id not in [k.id for k in kelas_list]:
            flash("Kelas tidak valid.", "danger")
            return redirect(url_for("dosen.tugas_baru"))
        judul = request.form.get("judul", "").strip()
        deskripsi = request.form.get("deskripsi", "").strip()
        deadline = request.form.get("deadline", "").strip()
        jenis = request.form.get("jenis", "tugas")
        bobot = request.form.get("bobot", type=int) or 10
        f = request.files.get("file")
        path = save_upload(f, "tugas") if f else None

        dl = None
        if deadline:
            try:
                dl = datetime.fromisoformat(deadline)
            except ValueError:
                pass

        db.session.add(Tugas(
            kelas_id=kelas_id, judul=judul, deskripsi=deskripsi,
            deadline=dl, file_path=path, jenis=jenis, bobot=bobot,
        ))
        db.session.commit()
        flash("Tugas dibuat.", "success")
        return redirect(url_for("dosen.tugas_list"))
    return render_template("dosen/tugas.html", kelas_list=kelas_list, view="form")


@bp.route("/tugas/<int:tid>")
def tugas_detail(tid):
    t = Tugas.query.get_or_404(tid)
    if t.kelas.dosen_id != current_user.id:
        abort(403)
    krs_aktif = KRS.query.filter_by(kelas_id=t.kelas_id, status="aktif").all()
    jawaban_map = {
        j.mahasiswa_id: j for j in
        JawabanTugas.query.filter_by(tugas_id=tid).all()
    }
    rows = []
    for k in krs_aktif:
        rows.append((k.mahasiswa, jawaban_map.get(k.mahasiswa_id)))
    return render_template("dosen/tugas.html", t=t, rows=rows, view="detail")


@bp.route("/jawaban/<int:jid>/nilai", methods=["POST"])
def beri_nilai(jid):
    j = JawabanTugas.query.get_or_404(jid)
    if j.tugas.kelas.dosen_id != current_user.id:
        abort(403)
    j.nilai = request.form.get("nilai", type=float)
    j.feedback = request.form.get("feedback", "").strip()
    db.session.commit()
    flash("Nilai disimpan.", "success")
    return redirect(url_for("dosen.tugas_detail", tid=j.tugas_id))


# ---------------------------------------------------------------------
# ABSENSI
# ---------------------------------------------------------------------
@bp.route("/absensi", methods=["GET", "POST"])
def absensi():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    selected_kelas = request.values.get("kelas_id", type=int)
    pertemuan = request.values.get("pertemuan", type=int) or 1
    tanggal_str = request.values.get("tanggal") or date.today().isoformat()

    rows = []
    if selected_kelas and selected_kelas in [k.id for k in kelas_list]:
        krs_aktif = KRS.query.filter_by(kelas_id=selected_kelas, status="aktif").all()
        existing = {
            a.mahasiswa_id: a for a in
            Absen.query.filter_by(kelas_id=selected_kelas, pertemuan_ke=pertemuan).all()
        }
        for k in krs_aktif:
            rows.append((k.mahasiswa, existing.get(k.mahasiswa_id)))

    if request.method == "POST" and selected_kelas:
        try:
            tgl = date.fromisoformat(tanggal_str)
        except ValueError:
            tgl = date.today()

        ALLOWED_STATUS = {"hadir", "izin", "sakit", "alpha"}

        for k in KRS.query.filter_by(kelas_id=selected_kelas, status="aktif").all():
            raw_status = request.form.get(f"status_{k.mahasiswa_id}", "hadir")
            # Validasi: pastikan status ada dalam daftar yang diizinkan
            status = raw_status if raw_status in ALLOWED_STATUS else "hadir"
            alasan = request.form.get(f"alasan_{k.mahasiswa_id}", "").strip()

            existing = Absen.query.filter_by(
                kelas_id=selected_kelas, mahasiswa_id=k.mahasiswa_id,
                pertemuan_ke=pertemuan,
            ).first()
            if existing:
                existing.status = status
                existing.alasan = alasan
                existing.tanggal = tgl
            else:
                db.session.add(Absen(
                    kelas_id=selected_kelas, mahasiswa_id=k.mahasiswa_id,
                    pertemuan_ke=pertemuan, tanggal=tgl,
                    status=status, alasan=alasan,
                ))
        db.session.commit()
        flash("Absensi tersimpan.", "success")
        return redirect(url_for(
            "dosen.absensi", kelas_id=selected_kelas, pertemuan=pertemuan,
        ))

    return render_template(
        "dosen/absensi.html", kelas_list=kelas_list, rows=rows,
        selected_kelas=selected_kelas, pertemuan=pertemuan,
        tanggal_str=tanggal_str,
    )


@bp.route("/absensi/rekap")
def absensi_rekap():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    selected_kelas = request.values.get("kelas_id", type=int)
    rekap = []
    pertemuan_count = 0
    if selected_kelas and selected_kelas in [k.id for k in kelas_list]:
        krs_aktif = KRS.query.filter_by(kelas_id=selected_kelas, status="aktif").all()
        absens = Absen.query.filter_by(kelas_id=selected_kelas).all()
        pertemuan_count = max([a.pertemuan_ke for a in absens], default=0)
        for k in krs_aktif:
            mhs_abs = [a for a in absens if a.mahasiswa_id == k.mahasiswa_id]
            rekap.append({
                "mhs": k.mahasiswa,
                "hadir": sum(1 for a in mhs_abs if a.status == "hadir"),
                "izin": sum(1 for a in mhs_abs if a.status == "izin"),
                "alpha": sum(1 for a in mhs_abs if a.status == "alpha"),
                "sakit": sum(1 for a in mhs_abs if a.status == "sakit"),
                "alasan_detail": [
                    f"Pertemuan {a.pertemuan_ke} ({a.status.capitalize()}): {a.alasan}"
                    for a in mhs_abs if a.status in ("izin", "sakit") and a.alasan
                ]
            })
    return render_template("dosen/absensi.html", kelas_list=kelas_list, rekap=rekap, selected_kelas=selected_kelas, pertemuan_count=pertemuan_count, view="rekap")


# ---------------------------------------------------------------------
# KONSELING
# ---------------------------------------------------------------------
@bp.route("/konseling")
def konseling_list():
    q = (
        KonselingThread.query
        .filter_by(dosen_id=current_user.id, deleted_by_dosen=False)
        .filter(KonselingThread.status != "ended")
        .order_by(KonselingThread.last_message_at.desc()).all()
    )
    pending = [t for t in q if t.status == "pending"]
    active = [t for t in q if t.status == "active"]
    # Dosen hanya bisa konseling dengan mahasiswa yang ada di kelasnya
    kelas_ids = _kelas_diampu_ids()
    mhs_ids = (
        db.session.query(KRS.mahasiswa_id)
        .filter(KRS.kelas_id.in_(kelas_ids), KRS.status == "aktif")
        .distinct().all()
    ) if kelas_ids else []
    mhs_id_set = {r[0] for r in mhs_ids}
    mahasiswa = (
        User.query.filter(
            User.id.in_(mhs_id_set),
            User.role == "mahasiswa",
            User.status == "aktif",
        ).order_by(User.nama).all()
    ) if mhs_id_set else []
    return render_template(
        "dosen/konseling.html", pending=pending, active=active, mahasiswa=mahasiswa,
    )


@bp.route("/konseling/history")
def konseling_history():
    """Riwayat tiket konseling yang sudah diakhiri — tidak dapat dihapus oleh
    pihak lain, hanya dirinya sendiri yg boleh menyembunyikan di list."""
    threads = (
        KonselingThread.query
        .filter_by(dosen_id=current_user.id, deleted_by_dosen=False, status="ended")
        .order_by(KonselingThread.ended_at.desc()).all()
    )
    return render_template("dosen/konseling.html", threads=threads, view="history")


@bp.route("/konseling/start", methods=["POST"])
def konseling_start():
    mhs_id = request.form.get("mahasiswa_id", type=int)
    topik = request.form.get("topik", "").strip() or None
    if not mhs_id:
        flash("Pilih mahasiswa.", "danger")
        return redirect(url_for("dosen.konseling_list"))
    target = User.query.filter_by(id=mhs_id, role="mahasiswa").first()
    if not target:
        flash("Mahasiswa tidak ditemukan.", "danger")
        return redirect(url_for("dosen.konseling_list"))
    # Validasi: hanya boleh konseling dengan mahasiswa di kelasnya
    kelas_ids = _kelas_diampu_ids()
    is_my_student = KRS.query.filter(
        KRS.mahasiswa_id == mhs_id,
        KRS.kelas_id.in_(kelas_ids),
        KRS.status == "aktif",
    ).first() if kelas_ids else None
    if not is_my_student:
        flash("Anda hanya bisa konseling dengan mahasiswa yang Anda ajar.", "danger")
        return redirect(url_for("dosen.konseling_list"))
    # Hanya ambil tiket yg MASIH BERJALAN. Tiket ``ended`` tetap tersimpan
    # terpisah sebagai history dan tidak diganggu.
    th = (
        KonselingThread.query
        .filter_by(mahasiswa_id=mhs_id, dosen_id=current_user.id)
        .filter(KonselingThread.status != "ended")
        .order_by(KonselingThread.created_at.desc())
        .first()
    )
    if th is None:
        th = KonselingThread(
            mahasiswa_id=mhs_id, dosen_id=current_user.id,
            topik=topik, opened_by="dosen",
            # Dosen yg membuka langsung active (tidak perlu ACC sendiri)
            status="active", accepted_at=datetime.utcnow(),
        )
        db.session.add(th)
    else:
        th.deleted_by_dosen = False
    db.session.commit()
    return redirect(url_for("dosen.konseling_chat", tid=th.id))


@bp.route("/konseling/<int:tid>", methods=["GET", "POST"])
def konseling_chat(tid):
    th = KonselingThread.query.filter_by(id=tid, dosen_id=current_user.id).first_or_404()
    if th.deleted_by_dosen:
        abort(404)
    if request.method == "POST":
        if th.status != "active":
            flash("Tiket belum/atau sudah tidak aktif. Tidak bisa kirim pesan.", "warning")
            return redirect(url_for("dosen.konseling_chat", tid=tid))
        isi = request.form.get("isi", "").strip()
        if isi:
            db.session.add(KonselingPesan(
                thread_id=tid, sender_id=current_user.id, isi=isi,
            ))
            th.last_message_at = datetime.utcnow()
            db.session.commit()
        return redirect(url_for("dosen.konseling_chat", tid=tid))
    pesan = KonselingPesan.query.filter_by(thread_id=tid).order_by(
        KonselingPesan.created_at.asc()
    ).all()
    return render_template("dosen/konseling.html", th=th, pesan=pesan, view="chat")


@bp.route("/konseling/<int:tid>/accept", methods=["POST"])
def konseling_accept(tid):
    """Dosen ACC tiket yg dibuka mahasiswa -> status active."""
    th = KonselingThread.query.filter_by(id=tid, dosen_id=current_user.id).first_or_404()
    if th.status == "pending":
        th.status = "active"
        th.accepted_at = datetime.utcnow()
        db.session.commit()
        flash("Tiket konseling di-ACC. Silakan mulai percakapan.", "success")
    return redirect(url_for("dosen.konseling_chat", tid=tid))


@bp.route("/konseling/<int:tid>/end", methods=["POST"])
def konseling_end(tid):
    """Akhiri tiket -> chat tidak bisa dikirim lagi, tiket pindah ke history."""
    th = KonselingThread.query.filter_by(id=tid, dosen_id=current_user.id).first_or_404()
    if th.status in ("pending", "active"):
        th.status = "ended"
        th.ended_at = datetime.utcnow()
        th.ended_by = "dosen"
        db.session.commit()
        flash("Tiket diakhiri. Riwayat tersimpan di history.", "info")
    return redirect(url_for("dosen.konseling_history"))


@bp.route("/konseling/<int:tid>/delete", methods=["POST"])
def konseling_delete(tid):
    """Hapus tampilan tiket HANYA di sisi dosen ini — mahasiswa tetap punya."""
    th = KonselingThread.query.filter_by(id=tid, dosen_id=current_user.id).first_or_404()
    th.deleted_by_dosen = True
    db.session.commit()
    flash("Riwayat tiket disembunyikan dari sisi Anda.", "info")
    return redirect(url_for("dosen.konseling_history"))


# ---------------------------------------------------------------------
# DAFTAR MAHASISWA — setiap dosen dapat melihat SEMUA mahasiswa di kampus
# (organisasi, nilai per semester, nama, NIM, nomor HP, email, dll.).
# ---------------------------------------------------------------------
@bp.route("/mahasiswa")
def list_mahasiswa():
    # Hanya tampilkan mahasiswa yang terdaftar di kelas yang diampu dosen ini.
    my_kelas_ids = set(_kelas_diampu_ids())
    taught_map = {}
    if my_kelas_ids:
        krs_rows = (
            db.session.query(KRS.mahasiswa_id, Kelas.kode_kelas, MataKuliah.nama)
            .select_from(KRS)
            .join(Kelas, KRS.kelas_id == Kelas.id)
            .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
            .filter(Kelas.dosen_id == current_user.id, KRS.status == "aktif")
            .all()
        )
        for mhs_id, kode, mk_nama in krs_rows:
            taught_map.setdefault(mhs_id, []).append(f"{mk_nama} ({kode})")
    # Ambil user hanya yang ada di taught_map
    mhs_ids = list(taught_map.keys())
    if mhs_ids:
        users = (
            User.query.filter(
                User.id.in_(mhs_ids),
                User.role == "mahasiswa",
                User.status == "aktif",
            ).order_by(User.nama).all()
        )
    else:
        users = []
    mhs_list = [(u, taught_map.get(u.id, [])) for u in users]
    return render_template("dosen/mahasiswa_list.html", mhs_list=mhs_list)


@bp.route("/mahasiswa/<int:uid>")
def mahasiswa_detail(uid):
    """Detail mahasiswa — hanya bisa diakses dosen yang mengajar mahasiswa tsb."""
    mhs = User.query.get_or_404(uid)
    if mhs.role != "mahasiswa":
        abort(404)

    # Pastikan dosen ini mengajar mahasiswa tersebut (ada di KRS aktif)
    kelas_ids = _kelas_diampu_ids()
    is_my_student = (
        KRS.query.filter(
            KRS.mahasiswa_id == uid,
            KRS.kelas_id.in_(kelas_ids),
            KRS.status == "aktif",
        ).first() if kelas_ids else None
    )
    if not is_my_student:
        flash("Anda tidak mengajar mahasiswa ini.", "warning")
        return redirect(url_for("dosen.list_mahasiswa"))

    # Nilai: semua nilai mahasiswa, dikelompokkan per semester
    nilai_rows = (
        db.session.query(Nilai, MataKuliah, Kelas)
        .join(Kelas, Nilai.kelas_id == Kelas.id)
        .join(MataKuliah, Kelas.matkul_id == MataKuliah.id)
        .filter(Nilai.mahasiswa_id == uid)
        .order_by(Nilai.semester.desc())
        .all()
    )
    nilai_per_sem = {}
    for n, mk, k in nilai_rows:
        nilai_per_sem.setdefault(n.semester, []).append((n, mk, k))

    # Rekap absensi: seluruh kelas (lintas dosen) supaya dosen lain punya
    # gambaran lengkap keaktifan mahasiswa.
    absen_rows = Absen.query.filter_by(mahasiswa_id=uid).all()
    absen_rekap = {
        "hadir": sum(1 for a in absen_rows if a.status == "hadir"),
        "izin": sum(1 for a in absen_rows if a.status == "izin"),
        "alpha": sum(1 for a in absen_rows if a.status == "alpha"),
        "sakit": sum(1 for a in absen_rows if a.status == "sakit"),
    }

    # Semua kelas yang diambil mahasiswa di KRS aktif
    mk_ambil = (
        db.session.query(MataKuliah, Kelas)
        .join(Kelas, MataKuliah.id == Kelas.matkul_id)
        .join(KRS, KRS.kelas_id == Kelas.id)
        .filter(KRS.mahasiswa_id == uid, KRS.status == "aktif")
        .all()
    )

    return render_template(
        "dosen/mahasiswa_detail.html", mhs=mhs,
        nilai_per_sem=nilai_per_sem, absen_rekap=absen_rekap,
        mk_ambil=mk_ambil,
    )


# ---------------------------------------------------------------------
# EVALUASI / NILAI per kelas (dosen menginput nilai)
# ---------------------------------------------------------------------
@bp.route("/nilai", methods=["GET", "POST"])
def nilai():
    from app.models import SystemSetting
    nilai_open = SystemSetting.get("nilai_open", "0") == "1"
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    selected_kelas = request.values.get("kelas_id", type=int)
    rows = []
    if selected_kelas and selected_kelas in [k.id for k in kelas_list]:
        krs_aktif = KRS.query.filter_by(kelas_id=selected_kelas, status="aktif").all()
        existing = {
            n.mahasiswa_id: n for n in
            Nilai.query.filter_by(kelas_id=selected_kelas).all()
        }
        for k in krs_aktif:
            rows.append((k.mahasiswa, existing.get(k.mahasiswa_id)))

    if request.method == "POST" and selected_kelas and nilai_open:
        for k in KRS.query.filter_by(kelas_id=selected_kelas, status="aktif").all():
            mid = k.mahasiswa_id
            n = Nilai.query.filter_by(
                kelas_id=selected_kelas, mahasiswa_id=mid,
            ).first()
            # Jika nilai sudah ada dan sudah dihitung → SKIP (locked)
            if n and n.nilai_akhir > 0:
                continue
            if not n:
                n = Nilai(
                    kelas_id=selected_kelas, mahasiswa_id=mid,
                    semester=k.semester,
                )
                db.session.add(n)
            for komp in ["kuis", "tugas", "uts", "uas", "keaktifan", "proyek"]:
                v = request.form.get(f"{komp}_{mid}", type=float)
                setattr(n, f"nilai_{komp}", v or 0)
            n.hitung()
        db.session.commit()
        flash("Nilai tersimpan. Nilai yang sudah diinput sebelumnya tidak bisa diubah.", "success")
        return redirect(url_for("dosen.nilai", kelas_id=selected_kelas))

    return render_template(
        "dosen/nilai.html", kelas_list=kelas_list, rows=rows,
        selected_kelas=selected_kelas, nilai_open=nilai_open,
        bobot=current_app.config["BOBOT_NILAI"],
    )


# ---------------------------------------------------------------------
# MATERI (konten belajar + YouTube)
# ---------------------------------------------------------------------
@bp.route("/materi")
def materi_list():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    selected_kelas = request.values.get("kelas_id", type=int)
    materi = []
    if selected_kelas and selected_kelas in [k.id for k in kelas_list]:
        materi = (
            Materi.query.filter_by(kelas_id=selected_kelas)
            .order_by(Materi.urutan.asc(), Materi.created_at.asc()).all()
        )
    return render_template(
        "dosen/materi.html", kelas_list=kelas_list,
        materi=materi, selected_kelas=selected_kelas,
    )


@bp.route("/materi/baru", methods=["GET", "POST"])
def materi_baru():
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    if request.method == "POST":
        kelas_id = request.form.get("kelas_id", type=int)
        if kelas_id not in [k.id for k in kelas_list]:
            flash("Kelas tidak valid.", "danger")
            return redirect(url_for("dosen.materi_baru"))
        judul = request.form.get("judul", "").strip()
        deskripsi = request.form.get("deskripsi", "").strip()
        youtube_url = request.form.get("youtube_url", "").strip()
        urutan = request.form.get("urutan", type=int) or 1
        f = request.files.get("file")
        path = None
        if f and f.filename:
            path = save_upload(f, "materi")
            if path is None:
                flash("Format file tidak didukung. Gunakan PDF, PPTX, PPT, DOCX, DOC, PNG, JPG.", "warning")

        if not judul:
            flash("Judul materi wajib diisi.", "danger")
            return redirect(url_for("dosen.materi_baru"))

        semester = request.form.get("semester", type=int) or 1
        db.session.add(Materi(
            kelas_id=kelas_id, judul=judul, deskripsi=deskripsi,
            youtube_url=youtube_url or None, file_path=path,
            urutan=urutan, semester=semester,
        ))
        db.session.commit()
        flash("Materi ditambahkan.", "success")
        return redirect(url_for("dosen.materi_list", kelas_id=kelas_id))
    return render_template("dosen/materi.html", kelas_list=kelas_list, m=None, view="form")


@bp.route("/materi/<int:mid>/edit", methods=["GET", "POST"])
def materi_edit(mid):
    m = Materi.query.get_or_404(mid)
    if m.kelas.dosen_id != current_user.id:
        abort(403)
    kelas_list = Kelas.query.filter_by(dosen_id=current_user.id).all()
    if request.method == "POST":
        m.judul = request.form.get("judul", m.judul).strip()
        m.deskripsi = request.form.get("deskripsi", "").strip()
        m.youtube_url = request.form.get("youtube_url", "").strip() or None
        m.urutan = request.form.get("urutan", type=int) or m.urutan
        m.semester = request.form.get("semester", type=int) or m.semester
        f = request.files.get("file")
        if f and f.filename:
            path = save_upload(f, "materi")
            if path:
                m.file_path = path
            else:
                flash("Format file tidak didukung. Gunakan PDF, PPTX, PPT, DOCX, DOC, PNG, JPG.", "warning")
        db.session.commit()
        flash("Materi diperbarui.", "success")
        return redirect(url_for("dosen.materi_list", kelas_id=m.kelas_id))
    return render_template("dosen/materi.html", kelas_list=kelas_list, m=m, view="form")


@bp.route("/materi/<int:mid>/delete", methods=["POST"])
def materi_delete(mid):
    m = Materi.query.get_or_404(mid)
    if m.kelas.dosen_id != current_user.id:
        abort(403)
    kelas_id = m.kelas_id
    db.session.delete(m)
    db.session.commit()
    flash("Materi dihapus.", "success")
    return redirect(url_for("dosen.materi_list", kelas_id=kelas_id))


# ---------------------------------------------------------------------
# LEADERBOARD TOP 10 MAHASISWA (per Prodi)
# ---------------------------------------------------------------------
@bp.route("/leaderboard")
def leaderboard():
    from app.models import Portfolio
    prodi_list = ProgramStudi.query.all()
    selected_prodi = request.values.get("prodi_id", type=int)
    jk_filter = request.values.get("jenis_kelas", "")
    top10 = []
    if selected_prodi:
        mhs_q = (
            db.session.query(User, ProfilMahasiswa)
            .join(ProfilMahasiswa, ProfilMahasiswa.user_id == User.id)
            .filter(ProfilMahasiswa.prodi_id == selected_prodi, User.status == "aktif")
        )
        if jk_filter in ("reguler", "nonreguler"):
            mhs_q = mhs_q.filter(ProfilMahasiswa.jenis_kelas == jk_filter)
        mhs_query = mhs_q.all()
        mhs_data = []
        for u, pm in mhs_query:
            nilai_list = Nilai.query.filter_by(mahasiswa_id=u.id).all()
            if not nilai_list:
                continue
            grade_map = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "E": 0.0}
            total_bobot = 0
            total_sks = 0
            for n in nilai_list:
                sks = n.kelas.matkul.sks if n.kelas and n.kelas.matkul else 3
                bobot = grade_map.get(n.grade, 0)
                total_bobot += bobot * sks
                total_sks += sks
            ipk = round(total_bobot / total_sks, 2) if total_sks > 0 else 0
            # Update IPK di profil
            pm.ipk = ipk
            portfolio = Portfolio.query.filter_by(mahasiswa_id=u.id).all()
            mhs_data.append({
                "user": u,
                "profil": pm,
                "ipk": ipk,
                "total_sks": total_sks,
                "semester_count": len(set(n.semester for n in nilai_list)),
                "organisasi": pm.organisasi,
                "portfolio": portfolio,
            })
        db.session.commit()
        mhs_data.sort(key=lambda x: x["ipk"], reverse=True)
        top10 = mhs_data[:10]
    return render_template(
        "dosen/leaderboard.html", prodi_list=prodi_list,
        top10=top10, selected_prodi=selected_prodi,
        jk_filter=jk_filter,
    )


# ---------------------------------------------------------------------
# PROFIL DOSEN
# ---------------------------------------------------------------------
@bp.route("/profile", methods=["GET", "POST"])
def profile():
    profil = current_user.profil_dosen
    if request.method == "POST":
        current_user.nama = request.form.get("nama", current_user.nama).strip()
        current_user.no_telp = request.form.get("no_telp", "").strip()
        current_user.alamat = request.form.get("alamat", "").strip()
        if profil:
            profil.jabatan = request.form.get("jabatan", "").strip()
            profil.riwayat_akademik = request.form.get("riwayat", "").strip()
        f = request.files.get("foto")
        path = save_upload(f, "profile", allow_image_only=True) if f else None
        if path:
            current_user.foto = path
        new_pw = request.form.get("password", "").strip()
        if new_pw:
            if len(new_pw) < 6:
                flash("Password baru min. 6 karakter.", "danger")
            else:
                current_user.set_password(new_pw)
        db.session.commit()
        flash("Profil diperbarui.", "success")
        return redirect(url_for("dosen.profile"))
    return render_template("dosen/profile.html", profil=profil)



