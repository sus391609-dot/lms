"""
app/mahasiswa/routes.py
=======================
Halaman & API untuk role mahasiswa.

Fitur yang ditangani:
- Dashboard ringkas (jadwal hari ini, tugas mendatang, notifikasi).
- Jadwal kuliah (semua kelas yang ada di KRS).
- Tugas (lihat & kirim jawaban max 20 MB).
- Nilai per semester.
- KRS (pilih kelas pada periode KRS terbuka).
- Pembayaran (upload bukti).
- Konseling (cross-prodi, semua dosen).
- Poin ke dosen (max 10/semester).
- Profil dosen yang mengajar.
- Profil mahasiswa.
- Organisasi (read-only, di-input oleh admin).
"""
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    abort, current_app, jsonify,
)
from flask_login import login_required, current_user

from app.extensions import db, csrf
from app.decorators import role_required
from app.models import (
    User, ProgramStudi, ProfilMahasiswa, ProfilDosen,
    MataKuliah, Kelas, Jadwal, KRS, Tugas, JawabanTugas,
    Absen, Nilai, Poin, KonselingThread, KonselingPesan,
    Pembayaran, Notifikasi, SystemSetting, Materi, Portfolio,
)
from app.utils import save_upload

bp = Blueprint("mahasiswa", __name__)


# ---------------------------------------------------------------------
@bp.before_request
@login_required
def _require_mahasiswa():
    if current_user.role != "mahasiswa" or current_user.status != "aktif":
        abort(403)


# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------
@bp.route("/")
@bp.route("/dashboard")
def dashboard():
    profil = current_user.profil_mahasiswa
    krs_list = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    kelas_ids = [k.kelas_id for k in krs_list]

    jadwal = (
        Jadwal.query.filter(Jadwal.kelas_id.in_(kelas_ids)).all()
        if kelas_ids else []
    )
    tugas = (
        Tugas.query.filter(Tugas.kelas_id.in_(kelas_ids))
        .order_by(Tugas.deadline.asc().nulls_last() if hasattr(Tugas.deadline, "asc") else Tugas.deadline)
        .limit(5).all()
        if kelas_ids else []
    )
    notifikasi = (
        Notifikasi.query.filter_by(user_id=current_user.id, dibaca=False)
        .order_by(Notifikasi.created_at.desc()).limit(5).all()
    )

    pembayaran = (
        Pembayaran.query.filter_by(mahasiswa_id=current_user.id)
        .order_by(Pembayaran.created_at.desc()).limit(3).all()
    )

    return render_template(
        "mahasiswa/dashboard.html",
        profil=profil, jadwal=jadwal, tugas=tugas,
        notifikasi=notifikasi, pembayaran=pembayaran,
        krs_count=len(krs_list),
    )


# ---------------------------------------------------------------------
# JADWAL
# ---------------------------------------------------------------------
@bp.route("/jadwal")
def jadwal():
    krs_list = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    kelas_ids = [k.kelas_id for k in krs_list]
    jadwal = (
        Jadwal.query.filter(Jadwal.kelas_id.in_(kelas_ids)).all()
        if kelas_ids else []
    )
    # Group by hari
    hari_order = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    grouped = {h: [] for h in hari_order}
    for j in jadwal:
        grouped.setdefault(j.hari, []).append(j)
    for h in grouped:
        grouped[h].sort(key=lambda j: j.jam_mulai)
    return render_template("mahasiswa/krs.html", grouped=grouped, hari_order=hari_order, view="jadwal")


# ---------------------------------------------------------------------
# TUGAS
# ---------------------------------------------------------------------
@bp.route("/tugas")
def tugas_list():
    krs_list = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    kelas_ids = [k.kelas_id for k in krs_list]
    tugas = (
        Tugas.query.filter(Tugas.kelas_id.in_(kelas_ids))
        .order_by(Tugas.created_at.desc()).all()
        if kelas_ids else []
    )
    # cari jawaban yang sudah dikirim
    jawaban_map = {
        j.tugas_id: j for j in
        JawabanTugas.query.filter_by(mahasiswa_id=current_user.id).all()
    }
    return render_template(
        "mahasiswa/tugas.html", tugas=tugas, jawaban_map=jawaban_map,
    )


@bp.route("/tugas/<int:tid>", methods=["GET", "POST"])
def tugas_detail(tid):
    t = Tugas.query.get_or_404(tid)
    # pastikan mahasiswa terdaftar di kelas ini
    if not KRS.query.filter_by(
        mahasiswa_id=current_user.id, kelas_id=t.kelas_id, status="aktif"
    ).first():
        abort(403)

    jawaban = JawabanTugas.query.filter_by(
        tugas_id=tid, mahasiswa_id=current_user.id
    ).first()

    if request.method == "POST":
        teks = request.form.get("teks", "").strip()
        f = request.files.get("file")
        path = save_upload(f, "jawaban") if f else None
        if not teks and not path:
            flash("Silakan isi teks atau upload file jawaban.", "danger")
            return redirect(url_for("mahasiswa.tugas_detail", tid=tid))
        if jawaban:
            jawaban.teks = teks or jawaban.teks
            if path:
                jawaban.file_path = path
            jawaban.submitted_at = datetime.utcnow()
        else:
            jawaban = JawabanTugas(
                tugas_id=tid, mahasiswa_id=current_user.id,
                teks=teks, file_path=path,
            )
            db.session.add(jawaban)
        db.session.commit()
        flash("Jawaban tersimpan.", "success")
        return redirect(url_for("mahasiswa.tugas_detail", tid=tid))

    return render_template("mahasiswa/tugas.html", t=t, jawaban=jawaban, view="detail")


# ---------------------------------------------------------------------
# NILAI
# ---------------------------------------------------------------------
@bp.route("/nilai")
def nilai():
    nilai_list = (
        Nilai.query.filter_by(mahasiswa_id=current_user.id)
        .order_by(Nilai.semester.desc()).all()
    )
    bobot = current_app.config["BOBOT_NILAI"]
    return render_template("mahasiswa/nilai.html", nilai_list=nilai_list, bobot=bobot)


# ---------------------------------------------------------------------
# KRS
# ---------------------------------------------------------------------
@bp.route("/krs", methods=["GET", "POST"])
def krs():
    profil = current_user.profil_mahasiswa
    krs_open = SystemSetting.get("krs_open", "0") == "1"
    # Kelas yang tersedia: matkul prodi mahasiswa & semester sesuai
    # PENTING: filter berdasarkan jenis_kelas mahasiswa (reguler/nonreguler)
    kelas_tersedia = (
        Kelas.query.join(MataKuliah)
        .filter(
            MataKuliah.prodi_id == profil.prodi_id,
            Kelas.jenis_kelas == (profil.jenis_kelas or "reguler"),
        )
        .all()
    )
    krs_aktif = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    sudah = {k.kelas_id for k in krs_aktif}

    if request.method == "POST":
        if not krs_open:
            flash("Periode KRS sedang ditutup admin.", "warning")
            return redirect(url_for("mahasiswa.krs"))
        kelas_ids = request.form.getlist("kelas_ids", type=int)
        # bersihkan KRS lama yang tidak dipilih
        for k in krs_aktif:
            if k.kelas_id not in kelas_ids:
                k.status = "dibatalkan"
        # tambah baru
        for kid in kelas_ids:
            if kid in sudah:
                continue
            kelas = Kelas.query.get(kid)
            if not kelas:
                continue
            jumlah = KRS.query.filter_by(kelas_id=kid, status="aktif").count()
            if jumlah >= kelas.kuota:
                flash(f"Kelas {kelas.label} sudah penuh.", "warning")
                continue
            db.session.add(KRS(
                mahasiswa_id=current_user.id, kelas_id=kid,
                semester=profil.semester,
            ))
        db.session.commit()
        flash("KRS tersimpan.", "success")
        return redirect(url_for("mahasiswa.krs"))

    return render_template(
        "mahasiswa/krs.html", kelas_tersedia=kelas_tersedia,
        sudah=sudah, krs_open=krs_open,
    )


# ---------------------------------------------------------------------
# PEMBAYARAN
# ---------------------------------------------------------------------
@bp.route("/pembayaran")
def pembayaran():
    bayar = (
        Pembayaran.query.filter_by(mahasiswa_id=current_user.id)
        .order_by(Pembayaran.created_at.desc()).all()
    )
    return render_template("mahasiswa/pembayaran.html", bayar=bayar)


@bp.route("/pembayaran/<int:bid>/upload", methods=["POST"])
def pembayaran_upload(bid):
    b = Pembayaran.query.filter_by(id=bid, mahasiswa_id=current_user.id).first_or_404()
    f = request.files.get("bukti")
    path = save_upload(f, "pembayaran")
    if not path:
        flash("File tidak valid.", "danger")
        return redirect(url_for("mahasiswa.pembayaran"))
    b.bukti = path
    b.status = "menunggu"
    db.session.commit()
    flash("Bukti diunggah, menunggu verifikasi admin.", "success")
    return redirect(url_for("mahasiswa.pembayaran"))


# ---------------------------------------------------------------------
# KONSELING
# ---------------------------------------------------------------------
@bp.route("/konseling")
def konseling_list():
    q = (
        KonselingThread.query
        .filter_by(mahasiswa_id=current_user.id, deleted_by_mhs=False)
        .filter(KonselingThread.status != "ended")
        .order_by(KonselingThread.last_message_at.desc()).all()
    )
    pending = [t for t in q if t.status == "pending"]
    active = [t for t in q if t.status == "active"]
    # Mahasiswa boleh konseling ke SEMUA dosen aktif (cross-prodi).
    semua_dosen = (
        User.query.filter_by(role="dosen", status="aktif").order_by(User.nama).all()
    )
    return render_template(
        "mahasiswa/konseling.html", pending=pending, active=active,
        semua_dosen=semua_dosen,
    )


@bp.route("/konseling/history")
def konseling_history():
    threads = (
        KonselingThread.query
        .filter_by(mahasiswa_id=current_user.id, deleted_by_mhs=False, status="ended")
        .order_by(KonselingThread.ended_at.desc()).all()
    )
    return render_template("mahasiswa/konseling.html", threads=threads, view="history")


@bp.route("/konseling/start", methods=["POST"])
def konseling_start():
    dosen_id = request.form.get("dosen_id", type=int)
    topik = request.form.get("topik", "").strip() or None
    if not dosen_id:
        flash("Pilih dosen.", "danger")
        return redirect(url_for("mahasiswa.konseling_list"))
    # Tiket aktif yg masih berjalan (pending/active). Jika ada, reuse saja.
    th = (
        KonselingThread.query
        .filter_by(mahasiswa_id=current_user.id, dosen_id=dosen_id)
        .filter(KonselingThread.status != "ended")
        .order_by(KonselingThread.created_at.desc())
        .first()
    )
    if th is None:
        # Belum ada tiket aktif -> buat baru. Tiket lama yg sudah ``ended``
        # tetap tersimpan terpisah sebagai history.
        th = KonselingThread(
            mahasiswa_id=current_user.id, dosen_id=dosen_id, topik=topik,
            status="pending", opened_by="mahasiswa",
        )
        db.session.add(th)
    else:
        th.deleted_by_mhs = False
    db.session.commit()
    if th.status == "pending":
        flash(
            "Tiket dikirim. Menunggu dosen untuk meng-ACC sebelum percakapan dimulai.",
            "info",
        )
    elif th.status == "active":
        flash("Tiket sudah aktif. Silakan lanjutkan percakapan.", "info")
    return redirect(url_for("mahasiswa.konseling_chat", tid=th.id))


@bp.route("/konseling/<int:tid>", methods=["GET", "POST"])
def konseling_chat(tid):
    th = KonselingThread.query.filter_by(id=tid, mahasiswa_id=current_user.id).first_or_404()
    if th.deleted_by_mhs:
        abort(404)
    if request.method == "POST":
        if th.status != "active":
            flash("Tiket belum/atau sudah tidak aktif. Tidak bisa kirim pesan.", "warning")
            return redirect(url_for("mahasiswa.konseling_chat", tid=tid))
        isi = request.form.get("isi", "").strip()
        if isi:
            db.session.add(KonselingPesan(
                thread_id=tid, sender_id=current_user.id, isi=isi,
            ))
            th.last_message_at = datetime.utcnow()
            db.session.commit()
        return redirect(url_for("mahasiswa.konseling_chat", tid=tid))
    pesan = KonselingPesan.query.filter_by(thread_id=tid).order_by(
        KonselingPesan.created_at.asc()
    ).all()
    return render_template("mahasiswa/konseling.html", th=th, pesan=pesan, view="chat")


@bp.route("/konseling/<int:tid>/end", methods=["POST"])
def konseling_end(tid):
    """Mahasiswa juga boleh mengakhiri tiket kapan pun."""
    th = KonselingThread.query.filter_by(id=tid, mahasiswa_id=current_user.id).first_or_404()
    if th.status in ("pending", "active"):
        th.status = "ended"
        th.ended_at = datetime.utcnow()
        th.ended_by = "mahasiswa"
        db.session.commit()
        flash("Tiket diakhiri. Riwayat tersimpan di history.", "info")
    return redirect(url_for("mahasiswa.konseling_history"))


@bp.route("/konseling/<int:tid>/delete", methods=["POST"])
def konseling_delete(tid):
    """Hapus tampilan tiket HANYA di sisi mahasiswa ini."""
    th = KonselingThread.query.filter_by(id=tid, mahasiswa_id=current_user.id).first_or_404()
    th.deleted_by_mhs = True
    db.session.commit()
    flash("Riwayat tiket disembunyikan dari sisi Anda.", "info")
    return redirect(url_for("mahasiswa.konseling_history"))


# ---------------------------------------------------------------------
# POIN KE DOSEN (max 10 / semester)
# ---------------------------------------------------------------------
@bp.route("/poin", methods=["GET", "POST"])
def poin():
    profil = current_user.profil_mahasiswa
    krs_list = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    dosen_ids = {k.kelas.dosen_id for k in krs_list}
    dosen_list = User.query.filter(User.id.in_(dosen_ids)).all() if dosen_ids else []

    diberikan = (
        Poin.query.filter_by(
            mahasiswa_id=current_user.id, semester=profil.semester,
        ).all()
    )
    total_terpakai = sum(p.nilai_poin for p in diberikan)
    sisa = max(0, current_app.config["POIN_PER_SEMESTER"] - total_terpakai)
    map_poin = {p.dosen_id: p for p in diberikan}

    if request.method == "POST":
        dosen_id = request.form.get("dosen_id", type=int)
        nilai = request.form.get("nilai", type=int)
        catatan = request.form.get("catatan", "").strip()
        if not dosen_id or nilai is None or nilai < 0:
            flash("Input tidak valid.", "danger")
            return redirect(url_for("mahasiswa.poin"))

        existing = map_poin.get(dosen_id)

        # ⛔ LOCK: jika poin sudah pernah diberikan, tidak bisa diubah
        if existing:
            flash("Poin sudah diberikan dan tidak dapat diubah.", "warning")
            return redirect(url_for("mahasiswa.poin"))

        new_total = total_terpakai + nilai
        if new_total > current_app.config["POIN_PER_SEMESTER"]:
            flash(
                f"Total poin melebihi {current_app.config['POIN_PER_SEMESTER']}.",
                "danger",
            )
            return redirect(url_for("mahasiswa.poin"))

        db.session.add(Poin(
            mahasiswa_id=current_user.id, dosen_id=dosen_id,
            nilai_poin=nilai, semester=profil.semester, catatan=catatan,
        ))
        db.session.commit()
        flash("Poin tersimpan dan terkunci. Tidak dapat diubah kembali.", "success")
        return redirect(url_for("mahasiswa.poin"))

    return render_template(
        "mahasiswa/poin.html", dosen_list=dosen_list,
        map_poin=map_poin, sisa=sisa,
        total=current_app.config["POIN_PER_SEMESTER"],
    )


# ---------------------------------------------------------------------
# DAFTAR DOSEN PENGAJAR (profil ringkas)
# ---------------------------------------------------------------------
@bp.route("/dosen")
def list_dosen():
    krs_list = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    dosen_ids = {k.kelas.dosen_id for k in krs_list}
    dosen_list = User.query.filter(User.id.in_(dosen_ids)).all() if dosen_ids else []
    return render_template("mahasiswa/poin.html", dosen_list=dosen_list, view="dosen_list")


# ---------------------------------------------------------------------
# MATERI (lihat konten belajar + YouTube embed)
# ---------------------------------------------------------------------
@bp.route("/materi")
def materi_list():
    krs_list = KRS.query.filter_by(mahasiswa_id=current_user.id, status="aktif").all()
    kelas_ids = [k.kelas_id for k in krs_list]
    selected_kelas = request.values.get("kelas_id", type=int)
    kelas_list = Kelas.query.filter(Kelas.id.in_(kelas_ids)).all() if kelas_ids else []
    materi = []
    if selected_kelas and selected_kelas in kelas_ids:
        materi = (
            Materi.query.filter_by(kelas_id=selected_kelas)
            .order_by(Materi.urutan.asc(), Materi.created_at.asc()).all()
        )
    return render_template(
        "mahasiswa/materi.html", kelas_list=kelas_list,
        materi=materi, selected_kelas=selected_kelas,
    )


@bp.route("/materi/<int:mid>")
def materi_detail(mid):
    m = Materi.query.get_or_404(mid)
    # pastikan mahasiswa terdaftar di kelas ini
    if not KRS.query.filter_by(
        mahasiswa_id=current_user.id, kelas_id=m.kelas_id, status="aktif"
    ).first():
        abort(403)
    return render_template("mahasiswa/materi.html", m=m, view="detail")


# ---------------------------------------------------------------------
# LEADERBOARD TOP 10 MAHASISWA (per Prodi)
# ---------------------------------------------------------------------
@bp.route("/leaderboard")
def leaderboard():
    prodi_list = ProgramStudi.query.all()
    selected_prodi = request.values.get("prodi_id", type=int)
    # Default ke prodi mahasiswa sendiri
    profil = current_user.profil_mahasiswa
    if not selected_prodi and profil:
        selected_prodi = profil.prodi_id
    top10 = []
    if selected_prodi:
        mhs_query = (
            db.session.query(User, ProfilMahasiswa)
            .join(ProfilMahasiswa, ProfilMahasiswa.user_id == User.id)
            .filter(ProfilMahasiswa.prodi_id == selected_prodi, User.status == "aktif")
            .all()
        )
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
        "mahasiswa/leaderboard.html", prodi_list=prodi_list,
        top10=top10, selected_prodi=selected_prodi,
    )


# ---------------------------------------------------------------------
# ORGANISASI (read-only)
# ---------------------------------------------------------------------
@bp.route("/organisasi")
def organisasi():
    profil = current_user.profil_mahasiswa
    return render_template("mahasiswa/profile.html", profil=profil, view="organisasi")


# ---------------------------------------------------------------------
# PROFIL
# ---------------------------------------------------------------------
@bp.route("/profile", methods=["GET", "POST"])
def profile():
    profil = current_user.profil_mahasiswa
    if request.method == "POST":
        current_user.nama = request.form.get("nama", current_user.nama).strip()
        current_user.no_telp = request.form.get("no_telp", "").strip()
        current_user.alamat = request.form.get("alamat", "").strip()
        f = request.files.get("foto")
        path = save_upload(f, "profile", allow_image_only=True) if f else None
        if path:
            current_user.foto = path
        # ganti password (opsional)
        new_pw = request.form.get("password", "").strip()
        if new_pw:
            if len(new_pw) < 6:
                flash("Password baru min. 6 karakter.", "danger")
            else:
                current_user.set_password(new_pw)
        db.session.commit()
        flash("Profil diperbarui.", "success")
        return redirect(url_for("mahasiswa.profile"))
    return render_template("mahasiswa/profile.html", profil=profil)


# ---------------------------------------------------------------------
# CHATBOT — rule-based assistant untuk mahasiswa
# ---------------------------------------------------------------------
@bp.route("/chatbot")
def chatbot():
    """Halaman UI chatbot."""
    return render_template("mahasiswa/chatbot.html")


def _chatbot_intent(text: str) -> dict:
    """
    Rule-based intent classifier sederhana.
    Mengembalikan {reply: str, links: [{label, href}]}.
    """
    t = (text or "").lower().strip()
    profil = current_user.profil_mahasiswa

    # Greeting
    if any(k in t for k in ["halo", "hai", "hi ", "hello", "assalam", "selamat"]):
        nama = current_user.nama.split(" ")[0] if current_user.nama else "Mahasiswa"
        return {
            "reply": (
                f"Halo {nama}! 👋 Saya asisten LMS Yarsi Pratama. "
                "Tanyakan saja seputar nilai, tugas, jadwal, KRS, "
                "pembayaran, konseling, atau organisasi."
            ),
            "links": [],
        }

    # NILAI
    if any(k in t for k in ["nilai", "ipk", "grade"]):
        nilai_list = (
            Nilai.query.filter_by(mahasiswa_id=current_user.id)
            .order_by(Nilai.semester.desc()).limit(5).all()
        )
        if not nilai_list:
            return {
                "reply": "Belum ada nilai yang diinput. Silakan hubungi dosen / admin "
                         "jika seharusnya sudah keluar.",
                "links": [{"label": "Buka halaman Nilai",
                           "href": url_for("mahasiswa.nilai")}],
            }
        rows = "\n".join(
            f"• Sem {n.semester} — {n.kelas.matkul.nama}: "
            f"{n.nilai_akhir or 0:.2f} ({n.grade or '-'})"
            for n in nilai_list
        )
        bobot = current_app.config["BOBOT_NILAI"]
        return {
            "reply": (
                f"Berikut 5 nilai terakhir kamu:\n{rows}\n\n"
                f"Bobot komponen: Kuis {bobot['kuis']}%, Tugas {bobot['tugas']}%, "
                f"UTS {bobot['uts']}%, UAS {bobot['uas']}%, "
                f"Keaktifan {bobot['keaktifan']}%, Proyek {bobot['proyek']}%."
            ),
            "links": [{"label": "Lihat semua nilai",
                       "href": url_for("mahasiswa.nilai")}],
        }

    # TUGAS
    if any(k in t for k in ["tugas", "deadline", "pekerjaan rumah", "pr "]):
        krs_list = KRS.query.filter_by(
            mahasiswa_id=current_user.id, status="aktif",
        ).all()
        kelas_ids = [k.kelas_id for k in krs_list]
        upcoming = []
        if kelas_ids:
            upcoming = (
                Tugas.query.filter(Tugas.kelas_id.in_(kelas_ids))
                .order_by(Tugas.deadline.asc()).limit(5).all()
            )
        if not upcoming:
            return {
                "reply": "Belum ada tugas aktif untuk kelasmu.",
                "links": [{"label": "Halaman Tugas",
                           "href": url_for("mahasiswa.tugas_list")}],
            }
        rows = "\n".join(
            f"• {tg.judul} — {tg.kelas.matkul.nama} "
            f"(deadline {tg.deadline.strftime('%d %b %Y %H:%M') if tg.deadline else '-'})"
            for tg in upcoming
        )
        return {
            "reply": (
                f"Tugas terdekat kamu:\n{rows}\n\n"
                "Format file yang diizinkan: pdf, docx, pptx, png, jpg, jpeg "
                "(maks 20 MB)."
            ),
            "links": [{"label": "Buka Tugas",
                       "href": url_for("mahasiswa.tugas_list")}],
        }

    # JADWAL
    if any(k in t for k in ["jadwal", "kelas hari", "kuliah hari"]):
        return {
            "reply": (
                "Kamu bisa cek jadwal lengkap per hari di halaman Jadwal. "
                "Jadwal otomatis tersusun dari KRS yang aktif."
            ),
            "links": [{"label": "Buka Jadwal",
                       "href": url_for("mahasiswa.jadwal")}],
        }

    # KRS
    if "krs" in t:
        krs_open = SystemSetting.get("krs_open", "0") == "1"
        status = "TERBUKA — kamu bisa memilih kelas sekarang." if krs_open \
            else "TERTUTUP — tunggu pengumuman dari admin."
        return {
            "reply": (
                f"Status periode KRS saat ini: {status}\n"
                "KRS dibuka oleh admin per periode. Pastikan IPK & semester memenuhi "
                "syarat sebelum mengambil mata kuliah."
            ),
            "links": [{"label": "Buka KRS",
                       "href": url_for("mahasiswa.krs")}],
        }

    # PEMBAYARAN
    if any(k in t for k in ["bayar", "tagihan", "pembayaran", "spp", "ukt"]):
        return {
            "reply": (
                "Untuk membayar, masuk ke halaman Pembayaran lalu upload bukti "
                "transfer. Status akan diverifikasi oleh admin."
            ),
            "links": [{"label": "Halaman Pembayaran",
                       "href": url_for("mahasiswa.pembayaran")}],
        }

    # KONSELING
    if any(k in t for k in ["konseling", "konsul", "curhat", "bimbing"]):
        return {
            "reply": (
                "Kamu bisa konseling dengan dosen mana pun di sistem (lintas prodi "
                "diperbolehkan). Buka thread baru dan kirim pesan; dosen akan "
                "merespon di inbox-nya."
            ),
            "links": [{"label": "Buka Konseling",
                       "href": url_for("mahasiswa.konseling_list")}],
        }

    # POIN
    if "poin" in t:
        sisa = current_app.config["POIN_PER_SEMESTER"]
        return {
            "reply": (
                f"Setiap semester kamu punya {sisa} poin untuk dibagikan ke "
                "dosen sebagai apresiasi. Poin di-reset tiap semester."
            ),
            "links": [{"label": "Halaman Poin",
                       "href": url_for("mahasiswa.poin")}],
        }

    # ORGANISASI
    if any(k in t for k in ["organisasi", "ukm", "bem", "himpunan"]):
        return {
            "reply": (
                "Daftar organisasi yang kamu ikuti diinput oleh admin "
                "berdasarkan keaktifan. Kamu bisa cek di halaman Organisasi."
            ),
            "links": [{"label": "Halaman Organisasi",
                       "href": url_for("mahasiswa.organisasi")}],
        }

    # PROFIL / FOTO
    if any(k in t for k in ["profil", "profile", "foto", "password", "ganti"]):
        return {
            "reply": (
                "Kamu bisa update nama, no telp, alamat, foto profil, dan "
                "password di halaman Profil. Upload foto: PNG/JPG, max 20 MB."
            ),
            "links": [{"label": "Halaman Profil",
                       "href": url_for("mahasiswa.profile")}],
        }

    # IPK / semester info
    if any(k in t for k in ["ipk saya", "semester saya", "siapa saya"]):
        ipk = profil.ipk if profil else None
        sem = profil.semester if profil else None
        return {
            "reply": (
                f"Data kamu: Semester {sem or '-'}, IPK {ipk if ipk is not None else '-'}.\n"
                "IPK akan otomatis terupdate setiap nilai baru tersimpan."
            ),
            "links": [],
        }

    # HELP
    if any(k in t for k in ["bantuan", "help", "menu", "fitur"]):
        return {
            "reply": (
                "Saya bisa bantu menjawab tentang:\n"
                "• Nilai & IPK\n• Tugas & deadline\n• Jadwal kuliah\n"
                "• KRS\n• Pembayaran\n• Konseling\n• Poin dosen\n"
                "• Organisasi\n• Profil & foto\n\n"
                "Coba ketik salah satu kata di atas."
            ),
            "links": [],
        }

    # FALLBACK
    return {
        "reply": (
            "Maaf, aku belum paham. Coba tanyakan dengan kata kunci seperti "
            "'nilai', 'tugas', 'jadwal', 'krs', 'pembayaran', 'konseling', "
            "'poin', 'organisasi', atau 'profil'."
        ),
        "links": [],
    }


@bp.route("/chatbot/ask", methods=["POST"])
@csrf.exempt
def chatbot_ask():
    """API JSON untuk chatbot — menerima {message: str}."""
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()
    if not msg:
        return jsonify({"reply": "Tulis pertanyaan kamu dulu ya.", "links": []})
    result = _chatbot_intent(msg)
    return jsonify(result)




