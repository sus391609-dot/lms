"""
app/mahasiswa/cv.py
===================
Generator Curriculum Vitae (CV) untuk role mahasiswa.

Fitur:
- Mengumpulkan seluruh data keaktifan mahasiswa: profil + identitas,
  pendidikan (prodi, angkatan, IPK, semester), organisasi, portfolio
  (prestasi/karya/sertifikasi/penghargaan), mata kuliah unggulan
  (nilai terbaik), pembayaran aktif (info administrasi singkat).
- Menghasilkan dua output:
    1. `/mahasiswa/cv`            – preview HTML (siap print)
    2. `/mahasiswa/cv.pdf`        – download PDF (format A4
       internasional, dua-kolom sidebar + main).
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from collections import defaultdict
from typing import Any

from flask import (
    Blueprint, render_template, send_file, current_app, url_for, abort
)
from flask_login import current_user, login_required

from app.decorators import role_required
from app.models import (
    Portfolio, Nilai, Kelas, KRS, ProfilMahasiswa, Pembayaran,
)


bp = Blueprint("mahasiswa_cv", __name__)


# ─────────────────────────────────────────────────────────────────────
# DATA AGGREGATOR
# ─────────────────────────────────────────────────────────────────────
def _kategori_label(k: str | None) -> str:
    """Mapping kategori portfolio → label CV yang rapi."""
    mapping = {
        "prestasi":    "Prestasi",
        "penghargaan": "Penghargaan",
        "sertifikasi": "Sertifikasi",
        "karya":       "Karya / Proyek",
        "lainnya":     "Pengalaman Lain",
    }
    return mapping.get((k or "lainnya").lower(), "Pengalaman Lain")


def collect_cv_data(user) -> dict[str, Any]:
    """Kumpulkan seluruh data keaktifan mahasiswa untuk CV.

    Return dictionary terstruktur supaya template & PDF builder sama
    sama bisa pakai.
    """
    profil = user.profil_mahasiswa

    # ── Portfolio (prestasi/karya/sertifikasi/penghargaan/lainnya) ──
    portfolio_rows = (
        Portfolio.query.filter_by(mahasiswa_id=user.id)
        .order_by(Portfolio.tahun.desc().nullslast(), Portfolio.created_at.desc())
        .all()
    )
    grouped: dict[str, list[Portfolio]] = defaultdict(list)
    for p in portfolio_rows:
        grouped[_kategori_label(p.kategori)].append(p)

    # ── Organisasi (free-text di ProfilMahasiswa) ───────────────────
    organisasi_lines: list[str] = []
    if profil and profil.organisasi:
        for line in profil.organisasi.splitlines():
            line = line.strip()
            if line:
                organisasi_lines.append(line)

    # ── Riwayat Akademik / Mata Kuliah Unggulan ─────────────────────
    nilai_rows = (
        Nilai.query.filter_by(mahasiswa_id=user.id)
        .order_by(Nilai.semester.asc(), Nilai.nilai_akhir.desc())
        .all()
    )
    # Best 6 courses (nilai akhir tertinggi) sebagai sorotan
    unggulan = sorted(
        [n for n in nilai_rows if n.nilai_akhir and n.nilai_akhir > 0],
        key=lambda n: n.nilai_akhir, reverse=True,
    )[:6]

    # Per-semester GPA snapshot
    by_sem: dict[int, list[Nilai]] = defaultdict(list)
    for n in nilai_rows:
        if n.nilai_akhir:
            by_sem[n.semester].append(n)
    semester_summary = []
    for sem in sorted(by_sem.keys()):
        items = by_sem[sem]
        if not items:
            continue
        avg = sum(n.nilai_akhir for n in items) / len(items)
        semester_summary.append({
            "semester": sem,
            "jumlah_mk": len(items),
            "rata2": round(avg, 2),
        })

    # ── KRS aktif (semester aktif) ──────────────────────────────────
    krs_aktif = (
        KRS.query.filter_by(mahasiswa_id=user.id, status="aktif").all()
    )
    sks_aktif = sum((k.kelas.matkul.sks if k.kelas and k.kelas.matkul else 0)
                    for k in krs_aktif)

    # ── Skor keaktifan sederhana (untuk badge "Aktif/Sangat Aktif") ─
    score = 0
    score += min(40, 8 * len(portfolio_rows))
    score += min(20, 6 * len(organisasi_lines))
    score += min(20, len(nilai_rows) * 2)
    score += min(20, 10 * len(unggulan[:3]))
    score = min(100, score)

    if score >= 80:
        keaktifan_label = "Sangat Aktif"
    elif score >= 55:
        keaktifan_label = "Aktif"
    elif score >= 30:
        keaktifan_label = "Cukup Aktif"
    else:
        keaktifan_label = "Mulai Aktif"

    # ── Skills (auto-derive dari kategori portfolio + organisasi) ───
    skills: list[str] = []
    for p in portfolio_rows:
        if p.kategori == "sertifikasi" and "TOEFL" in (p.judul or "").upper():
            skills.append("Bahasa Inggris (TOEFL)")
        if p.kategori == "sertifikasi" and "AWS" in (p.judul or "").upper():
            skills.append("AWS Cloud")
        if p.kategori == "karya" and "Flutter" in (p.deskripsi or ""):
            skills.append("Mobile Dev (Flutter)")
        if p.kategori == "karya" and "Flask" in (p.deskripsi or ""):
            skills.append("Backend (Flask / Python)")
        if p.kategori == "karya" and "React" in (p.deskripsi or ""):
            skills.append("Frontend (React)")
    # Tambahan default berdasarkan prodi
    if profil and profil.prodi:
        pname = profil.prodi.nama.lower()
        if "informatika" in pname or "ti" in pname:
            skills.extend([
                "Pemrograman Python", "Database SQL",
                "Pemecahan Masalah Algoritmik", "Pemodelan UML",
            ])
        elif "manajemen" in pname:
            skills.extend([
                "Analisis Bisnis", "Manajemen Proyek",
                "Microsoft Office", "Komunikasi Bisnis",
            ])
        elif "komunikasi" in pname:
            skills.extend([
                "Public Speaking", "Editing Video",
                "Copywriting", "Social Media Management",
            ])
        elif "kesehatan" in pname or "gizi" in pname or "kebidanan" in pname:
            skills.extend([
                "Asuhan Klinis", "Komunikasi Pasien",
                "Edukasi Kesehatan Masyarakat", "Dokumentasi Rekam Medis",
            ])
        else:
            skills.extend([
                "Kerja Tim", "Manajemen Waktu",
                "Adaptif & Berorientasi Hasil",
            ])
    # de-dup sambil pertahankan urutan
    seen: set[str] = set()
    dedup_skills: list[str] = []
    for s in skills:
        if s not in seen:
            seen.add(s)
            dedup_skills.append(s)
    skills = dedup_skills[:10]

    return {
        "user": user,
        "profil": profil,
        "portfolio": portfolio_rows,
        "portfolio_grouped": grouped,
        "organisasi": organisasi_lines,
        "nilai_unggulan": unggulan,
        "semester_summary": semester_summary,
        "krs_aktif": krs_aktif,
        "sks_aktif": sks_aktif,
        "skills": skills,
        "keaktifan_score": score,
        "keaktifan_label": keaktifan_label,
        "generated_at": datetime.utcnow(),
    }


# ─────────────────────────────────────────────────────────────────────
# ROUTE GUARD
# ─────────────────────────────────────────────────────────────────────
@bp.before_request
@login_required
def _require_mahasiswa():
    if current_user.role != "mahasiswa" or current_user.status != "aktif":
        abort(403)


# ─────────────────────────────────────────────────────────────────────
# HTML PREVIEW
# ─────────────────────────────────────────────────────────────────────
@bp.route("/cv")
def cv_preview():
    data = collect_cv_data(current_user)
    return render_template("mahasiswa/cv.html", **data)


# ─────────────────────────────────────────────────────────────────────
# PDF DOWNLOAD
# ─────────────────────────────────────────────────────────────────────
@bp.route("/cv.pdf")
def cv_pdf():
    data = collect_cv_data(current_user)
    buf = _build_cv_pdf(data)
    nim = (data["profil"].nim if data["profil"] else "mahasiswa")
    nama = (current_user.nama or "cv").replace(" ", "_")
    filename = f"CV_{nim}_{nama}.pdf"
    return send_file(
        buf, as_attachment=True,
        download_name=filename, mimetype="application/pdf",
    )


# =====================================================================
# PDF BUILDER (reportlab Platypus) — international CV layout
# =====================================================================
def _build_cv_pdf(data: dict[str, Any]) -> BytesIO:
    """Bangun PDF CV dengan layout dua-kolom modern (sidebar + main)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    from reportlab.platypus import (
        BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer,
        Table, TableStyle, FrameBreak, KeepInFrame, Image,
    )
    from reportlab.pdfgen import canvas as pdfcanvas
    import os

    # ── Brand colors ────────────────────────────────────────────────
    C_PRIMARY = colors.HexColor("#e94424")
    C_DARK    = colors.HexColor("#1a1a2e")
    C_TEXT    = colors.HexColor("#2d2d3a")
    C_MUTED   = colors.HexColor("#6b7280")
    C_LIGHT   = colors.HexColor("#fff3ee")
    C_BG_SIDE = colors.HexColor("#1a1a2e")
    C_SIDE_TX = colors.HexColor("#f3f4f6")
    C_SIDE_MT = colors.HexColor("#9ca3af")
    C_ACCENT  = colors.HexColor("#ff7a3d")

    buf = BytesIO()

    page_w, page_h = A4
    margin_x       = 14 * mm
    margin_y       = 14 * mm
    side_w         = 64 * mm
    gap            = 6 * mm
    main_x         = margin_x + side_w + gap
    main_w         = page_w - main_x - margin_x
    inner_y        = margin_y
    inner_h        = page_h - 2 * margin_y

    sidebar_frame = Frame(
        margin_x + 5 * mm, inner_y + 5 * mm,
        side_w - 10 * mm, inner_h - 10 * mm,
        showBoundary=0, leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0, id="sidebar",
    )
    main_frame = Frame(
        main_x, inner_y,
        main_w, inner_h,
        showBoundary=0, leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0, id="main",
    )
    # Continuation pages: full-width single column (no sidebar background)
    cont_full_w   = page_w - 2 * margin_x
    cont_top_band = 8 * mm  # reserve space at top for the orange accent
    cont_frame = Frame(
        margin_x, inner_y,
        cont_full_w, inner_h - cont_top_band,
        showBoundary=0, leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0, id="cont_main",
    )

    def _draw_first(canv: pdfcanvas.Canvas, doc):
        # Latar sidebar gelap (hanya halaman pertama)
        canv.setFillColor(C_BG_SIDE)
        canv.rect(margin_x, inner_y, side_w, inner_h, stroke=0, fill=1)
        # Bar oranye di atas sidebar
        canv.setFillColor(C_PRIMARY)
        canv.rect(margin_x, inner_y + inner_h - 8 * mm, side_w, 8 * mm,
                  stroke=0, fill=1)
        _draw_footer(canv)

    def _draw_cont(canv: pdfcanvas.Canvas, doc):
        # Aksen oranye tipis di atas (continuation page)
        canv.setFillColor(C_PRIMARY)
        canv.rect(margin_x, inner_y + inner_h - 4 * mm, cont_full_w, 4 * mm,
                  stroke=0, fill=1)
        _draw_footer(canv)

    def _draw_footer(canv: pdfcanvas.Canvas):
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(C_MUTED)
        footer = (
            f"Dihasilkan otomatis oleh portal mahasiswa "
            f"Universitas Yarsi Pratama — {data['generated_at'].strftime('%d %b %Y %H:%M UTC')}"
        )
        canv.drawString(margin_x, 8 * mm, footer)
        canv.drawRightString(
            page_w - margin_x, 8 * mm,
            f"Halaman {canv.getPageNumber()}",
        )

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=margin_x, rightMargin=margin_x,
        topMargin=margin_y, bottomMargin=margin_y,
        title=f"CV — {data['user'].nama}",
        author="Universitas Yarsi Pratama",
    )
    doc.addPageTemplates([
        PageTemplate(
            id="first",
            frames=[sidebar_frame, main_frame],
            onPage=_draw_first,
        ),
        PageTemplate(
            id="cont",
            frames=[cont_frame],
            onPage=_draw_cont,
        ),
    ])
    # Gunakan template kontinuasi untuk halaman ke-2 dst.
    from reportlab.platypus import NextPageTemplate

    # ── Styles ──────────────────────────────────────────────────────
    base_font   = "Helvetica"
    bold_font   = "Helvetica-Bold"
    italic_font = "Helvetica-Oblique"

    side_heading = ParagraphStyle(
        "side_heading", fontName=bold_font, fontSize=10,
        textColor=C_PRIMARY, alignment=TA_LEFT,
        spaceBefore=14, spaceAfter=4, leading=13, letterSpace=0.6,
    )
    side_text = ParagraphStyle(
        "side_text", fontName=base_font, fontSize=9,
        textColor=C_SIDE_TX, leading=12, alignment=TA_LEFT,
    )
    side_text_mute = ParagraphStyle(
        "side_text_mute", fontName=base_font, fontSize=8,
        textColor=C_SIDE_MT, leading=11, alignment=TA_LEFT,
    )
    name_style = ParagraphStyle(
        "name", fontName=bold_font, fontSize=15,
        textColor=C_SIDE_TX, leading=18, alignment=TA_LEFT,
        spaceAfter=2,
    )
    role_style = ParagraphStyle(
        "role", fontName=italic_font, fontSize=9,
        textColor=C_ACCENT, leading=12, alignment=TA_LEFT, spaceAfter=8,
    )

    main_heading = ParagraphStyle(
        "main_heading", fontName=bold_font, fontSize=12,
        textColor=C_PRIMARY, alignment=TA_LEFT,
        spaceBefore=6, spaceAfter=4, leading=15,
        borderPadding=0,
    )
    main_subheading = ParagraphStyle(
        "main_subheading", fontName=bold_font, fontSize=10.5,
        textColor=C_DARK, leading=13, alignment=TA_LEFT, spaceAfter=1,
    )
    main_meta = ParagraphStyle(
        "main_meta", fontName=italic_font, fontSize=8.5,
        textColor=C_MUTED, leading=11, alignment=TA_LEFT, spaceAfter=3,
    )
    main_text = ParagraphStyle(
        "main_text", fontName=base_font, fontSize=9.5,
        textColor=C_TEXT, leading=13, alignment=TA_LEFT, spaceAfter=4,
    )
    summary_text = ParagraphStyle(
        "summary_text", fontName=base_font, fontSize=10,
        textColor=C_TEXT, leading=14, alignment=TA_LEFT, spaceAfter=6,
    )
    badge_text = ParagraphStyle(
        "badge_text", fontName=bold_font, fontSize=8,
        textColor=colors.whitesmoke, alignment=TA_CENTER,
        leading=10,
    )

    # ── SIDEBAR CONTENT ─────────────────────────────────────────────
    story: list = []
    # Switch to continuation page template AFTER page 1 is rendered.
    story.append(NextPageTemplate("cont"))
    user    = data["user"]
    profil  = data["profil"]
    prodi   = profil.prodi if profil else None

    # Foto / inisial
    foto_path = None
    if user.foto:
        try:
            static_root = os.path.join(
                current_app.root_path, "..", "static"
            )
            candidate = os.path.normpath(os.path.join(static_root, user.foto))
            if os.path.isfile(candidate):
                foto_path = candidate
        except Exception:
            foto_path = None

    if foto_path:
        # Frame photo — kotak rounded simulasi via Image (reportlab gak
        # support rounded native, jadi pakai Image biasa).
        try:
            img = Image(foto_path, width=44 * mm, height=44 * mm)
            img.hAlign = "LEFT"
            story.append(img)
        except Exception:
            pass
    else:
        # Inisial placeholder
        initial = (user.nama or "M")[0].upper()
        placeholder = Table(
            [[Paragraph(f"<b>{initial}</b>",
                ParagraphStyle("init", fontName=bold_font, fontSize=30,
                               textColor=C_PRIMARY, alignment=TA_CENTER,
                               leading=34))]],
            colWidths=[44 * mm], rowHeights=[44 * mm],
        )
        placeholder.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), C_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0, colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(placeholder)
    story.append(Spacer(1, 6))

    # Nama & prodi
    story.append(Paragraph(user.nama or "-", name_style))
    if prodi:
        story.append(Paragraph(
            f"{prodi.nama} &middot; {prodi.fakultas}", role_style
        ))
    else:
        story.append(Paragraph("Mahasiswa Universitas Yarsi Pratama", role_style))

    # Keaktifan badge
    badge_color = C_ACCENT if data["keaktifan_score"] >= 55 else colors.HexColor("#6b7280")
    badge = Table(
        [[Paragraph(data["keaktifan_label"].upper(), badge_text)]],
        colWidths=[36 * mm], rowHeights=[6.5 * mm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), badge_color),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(badge)
    story.append(Spacer(1, 4))

    # ── Contact
    story.append(Paragraph("CONTACT", side_heading))
    contact_lines: list[str] = []
    if user.email:
        contact_lines.append(f"<b>Email:</b> {user.email}")
    if user.no_telp:
        contact_lines.append(f"<b>Phone:</b> {user.no_telp}")
    if user.alamat:
        contact_lines.append(f"<b>Address:</b> {user.alamat}")
    if not contact_lines:
        contact_lines.append("<i>(belum diisi di profil)</i>")
    for ln in contact_lines:
        story.append(Paragraph(ln, side_text))
        story.append(Spacer(1, 2))

    # ── Education snapshot
    story.append(Paragraph("EDUCATION", side_heading))
    if profil and prodi:
        story.append(Paragraph(
            f"<b>{prodi.nama}</b>", side_text,
        ))
        story.append(Paragraph(
            f"{prodi.fakultas}<br/>Universitas Yarsi Pratama",
            side_text_mute,
        ))
        story.append(Spacer(1, 2))
        edu_meta = [
            f"NIM: {profil.nim}",
            f"Angkatan: {profil.angkatan}",
            f"Semester: {profil.semester}",
        ]
        if profil.ipk:
            edu_meta.append(f"GPA: <b>{profil.ipk:.2f}</b> / 4.00")
        story.append(Paragraph("<br/>".join(edu_meta), side_text))
    else:
        story.append(Paragraph("Profil belum lengkap.", side_text_mute))

    # ── Skills
    if data["skills"]:
        story.append(Paragraph("SKILLS", side_heading))
        for s in data["skills"]:
            story.append(Paragraph(f"• {s}", side_text))
            story.append(Spacer(1, 1))

    # ── Languages (default)
    story.append(Paragraph("LANGUAGES", side_heading))
    story.append(Paragraph("• Bahasa Indonesia — Native", side_text))
    has_english = any("TOEFL" in (p.judul or "").upper() or "IELTS" in (p.judul or "").upper()
                      for p in data["portfolio"])
    eng_lvl = "Professional" if has_english else "Intermediate"
    story.append(Paragraph(f"• English — {eng_lvl}", side_text))

    # ── Generated info
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"<i>Generated: {data['generated_at'].strftime('%d %b %Y')}</i>",
        side_text_mute,
    ))

    # Pindah ke kolom utama
    story.append(FrameBreak())

    # ── MAIN COLUMN CONTENT ─────────────────────────────────────────
    # Header — name (besar) + tagline
    story.append(Paragraph(
        f"<font color='#1a1a2e'>{(user.nama or 'Mahasiswa').upper()}</font>",
        ParagraphStyle("name_big", fontName=bold_font, fontSize=22,
                       textColor=C_DARK, leading=24, spaceAfter=2),
    ))
    tagline_bits: list[str] = []
    if prodi:
        tagline_bits.append(prodi.nama)
    tagline_bits.append("Universitas Yarsi Pratama")
    story.append(Paragraph(
        " &nbsp;|&nbsp; ".join(tagline_bits),
        ParagraphStyle("tagline", fontName=base_font, fontSize=10,
                       textColor=C_PRIMARY, leading=13, spaceAfter=10),
    ))

    # Garis pemisah
    sep = Table([[""]], colWidths=[main_w - 2], rowHeights=[1.2])
    sep.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_PRIMARY),
    ]))
    story.append(sep)
    story.append(Spacer(1, 8))

    # Profile summary
    story.append(Paragraph("PROFILE", main_heading))
    summary_lines: list[str] = []
    if prodi:
        summary_lines.append(
            f"Mahasiswa aktif Program Studi <b>{prodi.nama}</b>, "
            f"Fakultas {prodi.fakultas}, Universitas Yarsi Pratama, "
            f"angkatan {profil.angkatan if profil else '-'} "
            f"(semester {profil.semester if profil else '-'})."
        )
    if profil and profil.ipk:
        summary_lines.append(
            f"Indeks Prestasi Kumulatif (IPK) terkini "
            f"<b>{profil.ipk:.2f}</b> dari 4.00."
        )
    summary_lines.append(
        f"Memiliki <b>{len(data['portfolio'])}</b> portofolio yang terdiri dari "
        f"prestasi, karya, sertifikasi, dan penghargaan, serta aktif "
        f"di <b>{len(data['organisasi'])}</b> organisasi/peran kampus. "
        f"Berdasarkan rekam keaktifan, dinilai sebagai mahasiswa "
        f"<b>{data['keaktifan_label']}</b> (skor {data['keaktifan_score']}/100)."
    )
    for ln in summary_lines:
        story.append(Paragraph(ln, summary_text))

    # ── Education detail
    story.append(Paragraph("EDUCATION", main_heading))
    if profil and prodi:
        edu_left = Paragraph(
            f"<b>{prodi.nama}</b><br/>"
            f"{prodi.fakultas} — Universitas Yarsi Pratama",
            main_subheading,
        )
        edu_right = Paragraph(
            f"NIM {profil.nim}<br/>Angkatan {profil.angkatan}",
            ParagraphStyle("edu_right", parent=main_meta, alignment=TA_RIGHT),
        )
        edu_tbl = Table(
            [[edu_left, edu_right]],
            colWidths=[main_w * 0.66, main_w * 0.34],
        )
        edu_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(edu_tbl)
        edu_details: list[str] = []
        if profil.ipk:
            edu_details.append(f"IPK: <b>{profil.ipk:.2f}</b> / 4.00")
        edu_details.append(f"Semester aktif: {profil.semester}")
        if data["sks_aktif"]:
            edu_details.append(f"SKS aktif: {data['sks_aktif']}")
        edu_details.append(f"Jenis Kelas: {profil.jenis_kelas.title()}")
        story.append(Paragraph(" &nbsp;|&nbsp; ".join(edu_details), main_meta))
    else:
        story.append(Paragraph(
            "<i>Data profil belum lengkap.</i>", main_meta,
        ))

    # ── GPA per semester
    if data["semester_summary"]:
        story.append(Spacer(1, 4))
        rows = [["Semester", "Jumlah MK", "Rata-rata Nilai"]]
        for s in data["semester_summary"]:
            rows.append([
                f"Semester {s['semester']}",
                str(s["jumlah_mk"]),
                f"{s['rata2']:.2f}",
            ])
        tbl = Table(rows, colWidths=[main_w * 0.40, main_w * 0.25, main_w * 0.35])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_LIGHT),
            ("TEXTCOLOR",  (0, 0), (-1, 0), C_PRIMARY),
            ("FONTNAME",   (0, 0), (-1, 0), bold_font),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("ALIGN",      (1, 0), (-1, -1), "CENTER"),
            ("ALIGN",      (0, 0), (0, -1),  "LEFT"),
            ("LINEBELOW",  (0, 0), (-1, 0),  0.6, C_PRIMARY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
                [colors.whitesmoke, colors.HexColor("#fafafa")]),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
        ]))
        story.append(tbl)

    # ── Mata kuliah unggulan
    if data["nilai_unggulan"]:
        story.append(Paragraph("KEY COURSES", main_heading))
        for n in data["nilai_unggulan"]:
            mk = n.kelas.matkul if n.kelas and n.kelas.matkul else None
            if not mk:
                continue
            row_left = Paragraph(
                f"<b>{mk.nama}</b> &middot; <font color='#6b7280'>{mk.kode}</font>",
                main_text,
            )
            row_right = Paragraph(
                f"<b>{n.grade}</b> &nbsp; ({n.nilai_akhir:.1f})",
                ParagraphStyle("grade", parent=main_text,
                               alignment=TA_RIGHT, fontName=bold_font,
                               textColor=C_PRIMARY),
            )
            tbl = Table(
                [[row_left, row_right]],
                colWidths=[main_w * 0.72, main_w * 0.28],
            )
            tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(tbl)

    # ── Organisasi
    if data["organisasi"]:
        story.append(Paragraph("ORGANIZATIONAL EXPERIENCE", main_heading))
        for line in data["organisasi"]:
            story.append(Paragraph(f"• {line}", main_text))

    # ── Portfolio per kategori (Prestasi → Penghargaan → Sertifikasi → Karya → Pengalaman)
    order = ["Prestasi", "Penghargaan", "Sertifikasi", "Karya / Proyek", "Pengalaman Lain"]
    section_titles = {
        "Prestasi":       "ACHIEVEMENTS",
        "Penghargaan":    "AWARDS",
        "Sertifikasi":    "CERTIFICATIONS",
        "Karya / Proyek": "PROJECTS",
        "Pengalaman Lain": "OTHER EXPERIENCE",
    }
    for kat in order:
        rows = data["portfolio_grouped"].get(kat) or []
        if not rows:
            continue
        story.append(Paragraph(section_titles[kat], main_heading))
        for p in rows:
            head_left = Paragraph(f"<b>{p.judul}</b>", main_subheading)
            head_right = Paragraph(
                f"{p.tahun or '-'}",
                ParagraphStyle("yr", parent=main_meta, alignment=TA_RIGHT,
                               fontName=bold_font, textColor=C_PRIMARY),
            )
            tbl = Table(
                [[head_left, head_right]],
                colWidths=[main_w * 0.78, main_w * 0.22],
            )
            tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(tbl)
            if p.deskripsi:
                story.append(Paragraph(p.deskripsi, main_text))
            story.append(Spacer(1, 3))

    # Build
    doc.build(story)
    buf.seek(0)
    return buf
