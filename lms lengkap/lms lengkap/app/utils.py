"""
app/utils.py
============
Kumpulan helper utility untuk LMS.

Menggabungkan tiga modul sebelumnya (audit, email, files) menjadi satu file
agar struktur project lebih ringkas.

Fungsi yang tersedia:
- record_audit(aksi, target, detail)     — pencatat audit log
- generate_code(length)                  — generate kode OTP numerik
- send_email(to, subject, html_body)     — kirim email via SMTP
- send_verification_code(email, code, purpose) — kirim kode verifikasi
- save_upload(file_storage, subdir, allow_image_only) — simpan file upload
"""
from __future__ import annotations

# ── Audit ──────────────────────────────────────────────────────────────────
import os
import random
import secrets
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import current_app
from flask_login import current_user
from werkzeug.utils import secure_filename


def record_audit(aksi: str, target: str | None = None, detail: str | None = None) -> None:
    """Tambah entri audit ke session DB (belum commit).

    Super admin dikecualikan — tidak ada jejaknya di audit log.
    Fungsi aman dipanggil tanpa user login (user_id=None).
    """
    from app.extensions import db
    from app.models import AuditLog

    if getattr(current_user, "is_authenticated", False):
        if getattr(current_user, "role", None) == "superadmin":
            return  # superadmin tidak tercatat
        uid = current_user.id
    else:
        uid = None

    db.session.add(AuditLog(user_id=uid, aksi=aksi, target=target, detail=detail))


# ── Email ──────────────────────────────────────────────────────────────────

def generate_code(length: int = 6) -> str:
    """Hasilkan kode OTP numerik acak."""
    return "".join(str(random.randint(0, 9)) for _ in range(length))


def send_email(to: str, subject: str, html_body: str) -> bool:
    """Kirim email HTML ke ``to``. Return True bila berhasil."""
    cfg = current_app.config

    if cfg.get("SMTP_DISABLED"):
        current_app.logger.info(
            "SMTP_DISABLED=1, skip kirim email. To=%s Subject=%s", to, subject
        )
        return True

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=20) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.sendmail(cfg["SMTP_USER"], [to], msg.as_string())
        current_app.logger.info("Email sent OK. To=%s Subject=%s", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.error(
            "Gagal kirim email ke %s (host=%s:%s user=%s): %s",
            to, cfg.get("SMTP_HOST"), cfg.get("SMTP_PORT"), cfg.get("SMTP_USER"), exc,
        )
        return False


def send_verification_code(email: str, code: str, purpose: str = "register") -> bool:
    """Kirim kode verifikasi OTP 6 digit. purpose = 'register' | 'reset'."""
    judul = (
        "Verifikasi Akun LMS Universitas Yarsi Pratama"
        if purpose == "register"
        else "Reset Password LMS Universitas Yarsi Pratama"
    )
    teks_judul = "Verifikasi Akun Anda" if purpose == "register" else "Reset Password Anda"
    teks_pembuka = (
        "Selamat datang di LMS Universitas Yarsi Pratama!"
        if purpose == "register"
        else "Anda meminta untuk mereset password akun Anda."
    )
    teks_aksi = "menyelesaikan pendaftaran" if purpose == "register" else "mengganti password"
    digit_html = "".join(
        f'<span style="display:inline-block; min-width:42px; padding:14px 6px; '
        f'margin:0 4px; border-radius:10px; background:#fff3ee; color:#ff5f1a; '
        f'font-size:30px; font-weight:800; letter-spacing:2px; '
        f'border:1px solid #ffd5c0;">{d}</span>'
        for d in code
    )
    body = f"""\
<!doctype html>
<html lang="id">
  <body style="margin:0; padding:0; background:#f6f7fb;
               font-family:Inter,Segoe UI,Arial,sans-serif; color:#111827;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0"
           width="100%" style="background:#f6f7fb; padding:32px 12px;">
      <tr><td align="center">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0"
               width="560" style="max-width:560px; background:#ffffff;
                                  border:1px solid #ffd5c0; border-radius:18px;
                                  overflow:hidden; box-shadow:0 8px 24px rgba(255,95,26,0.08);">
          <tr><td style="background:linear-gradient(135deg,#ff7a3d,#ff5f1a);
                         color:#ffffff; padding:28px 28px 22px;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
              <td style="vertical-align:middle;">
                <div style="display:inline-block; width:42px; height:42px;
                            border-radius:10px; background:rgba(255,255,255,0.18);
                            text-align:center; line-height:42px; font-weight:800;
                            letter-spacing:1px; font-size:16px; color:#ffffff;
                            margin-right:12px;">YP</div>
              </td>
              <td style="vertical-align:middle;">
                <div style="font-size:18px; font-weight:700;">Universitas Yarsi Pratama</div>
                <div style="font-size:13px; opacity:0.9;">Learning Management System</div>
              </td>
            </tr></table>
            <h1 style="margin:18px 0 4px; font-size:22px; font-weight:700;">{teks_judul}</h1>
            <p style="margin:0; font-size:13px; opacity:0.95;">
              Kode keamanan satu kali (OTP) untuk akun {email}
            </p>
          </td></tr>
          <tr><td style="padding:28px;">
            <p style="margin:0 0 12px; font-size:15px; line-height:1.6;">Halo,</p>
            <p style="margin:0 0 16px; font-size:15px; line-height:1.6;">
              {teks_pembuka} Gunakan kode 6 digit di bawah ini untuk
              {teks_aksi}. Kode hanya berlaku <b>15 menit</b>.
            </p>
            <div style="text-align:center; margin:22px 0 18px;">{digit_html}</div>
            <p style="margin:0 0 8px; font-size:13px; color:#6b7280; text-align:center;">
              Salin kode ini dan tempelkan pada halaman verifikasi LMS.
            </p>
            <hr style="border:none; border-top:1px solid #f1d4c2; margin:22px 0;">
            <div style="background:#fff8f3; border:1px solid #ffd5c0;
                        border-radius:10px; padding:14px 16px;">
              <div style="font-weight:700; font-size:13px; color:#ff5f1a; margin-bottom:4px;">
                Tips Keamanan
              </div>
              <ul style="margin:0; padding-left:18px; font-size:13px; color:#374151; line-height:1.6;">
                <li>Jangan bagikan kode ini kepada siapa pun, termasuk staf kampus.</li>
                <li>LMS Yarsi Pratama tidak akan pernah meminta kode lewat telepon.</li>
                <li>Bila Anda tidak meminta {teks_aksi}, abaikan email ini.</li>
              </ul>
            </div>
          </td></tr>
          <tr><td style="background:#fafafa; padding:16px 28px; text-align:center;
                         font-size:12px; color:#6b7280; border-top:1px solid #f1d4c2;">
            &copy; Universitas Yarsi Pratama &middot; LMS Akademik<br>
            Email otomatis &mdash; mohon tidak membalas pesan ini.
          </td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""
    return send_email(email, judul, body)


# ── File upload ────────────────────────────────────────────────────────────

def _allowed(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


def save_upload(file_storage, subdir: str, allow_image_only: bool = False) -> str | None:
    """Simpan file_storage ke static/uploads/<subdir>.

    Return path relatif (uploads/<subdir>/<unique>.<ext>) untuk disimpan di DB,
    atau None bila file kosong/invalid.
    """
    if not file_storage:
        return None
    if not file_storage.filename or file_storage.filename.strip() == "":
        return None
    filename = secure_filename(file_storage.filename)
    if not filename or "." not in filename:
        return None
    if not _allowed(filename):
        return None
    ext = filename.rsplit(".", 1)[1].lower()
    if allow_image_only and ext not in {"png", "jpg", "jpeg"}:
        return None

    uniq = secrets.token_hex(8)
    new_name = f"{uniq}.{ext}"
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(folder, exist_ok=True)
    try:
        file_storage.save(os.path.join(folder, new_name))
    except Exception:
        return None
    return f"uploads/{subdir}/{new_name}"
