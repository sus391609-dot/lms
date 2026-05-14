---
name: testing-lms-exam
description: Test the LMS exam system (ujian online) end-to-end. Use when verifying exam creation, exam taking, scoring, anti-cheat, PMB page, or demo data changes.
---

# Testing LMS Exam System

## Prerequisites

- Python virtualenv at `/home/ubuntu/lms/.venv/bin/activate`
- App directory: `/home/ubuntu/lms/lms lengkap/lms lengkap/`
- Start server: `cd "/home/ubuntu/lms/lms lengkap/lms lengkap" && source /home/ubuntu/lms/.venv/bin/activate && python run.py`
- The app runs on `http://127.0.0.1:5000`
- Database: SQLite at `instance/lms.db` (auto-created with demo data on first run)

## Devin Secrets Needed

None required — all demo accounts use hardcoded passwords.

## Demo Accounts

| Role | Email | Password |
|------|-------|----------|
| Dosen | `budi.santoso@yarsipratama.ac.id` | `dosen123` |
| Mahasiswa (TI) | `andi@student.yarsipratama.ac.id` | `mhs123` |
| Mahasiswa (Manajemen) | `siti@student.yarsipratama.ac.id` | `mhs123` |

All 16 demo mahasiswa accounts use password `mhs123`.

## Key Test Flows

### 1. Dosen Exam Management
- Login as dosen → sidebar "Ujian Online"
- Bank Soal page shows existing exams with token, soal count, status
- Click "Soal" to view/add questions (PG with A-E options, or Esai with kunci jawaban)
- Click "Hasil" to view student submissions with scores and tab-leave counts
- "Buat Ujian Baru" creates exam with auto-generated 8-char token

### 2. Mahasiswa Exam Taking
- Login as mahasiswa → sidebar "Ujian Online"
- "Ujian yang Tersedia" table shows exams matching KRS enrollment
- Enter token → fullscreen exam page with timer, nav sidebar, question display
- PG: click option to select, Esai: type in textarea
- "Ragu-Ragu" toggle gives 50% of bobot regardless of answer correctness
- "Kumpulkan Jawaban" submits and shows score immediately
- Results page: score summary + per-soal detail with green/red indicators

### 3. Scoring Verification
- PG correct (no ragu): full bobot points
- PG wrong (no ragu): 0 points
- Any answer with ragu: bobot / 2 points
- Esai: keyword matching (case-insensitive, checks if kunci appears in answer)
- Score formula: (total earned / total bobot) × 100

### 4. Account Isolation
- Students only see exams for classes they're enrolled in (via KRS)
- Non-enrolled student entering valid token gets: "Anda tidak terdaftar di kelas ini"
- Use Siti (S1 Manajemen) to test isolation against TI exams

### 5. Sidebar Integration Check
- Programmatically test all sidebar pages return 200:
  - 11 dosen pages, 17 mahasiswa pages
  - Use Flask test client with `WTF_CSRF_ENABLED = False`

### 6. PMB Page
- Visit `/pmb/` (public, no login)
- Sections to verify: Hero, Keunggulan, Beasiswa, Alur, Syarat, Formulir, Kehidupan Kampus (gallery), Berita & Kegiatan (news cards), FAQ
- Gallery has 4 demo campus images, news has 3 demo cards

## Tips

- The exam page goes fullscreen on entry — browser testing tools may trigger visibility change events
- Demo exam token might change if database is recreated — check the bank soal page for current token
- Tab leave detection relies on `visibilitychange` and `blur` events — automated browser tools may not trigger these the same way a human would
- When testing via Flask test client, disable CSRF: `app.config['WTF_CSRF_ENABLED'] = False`
- The app uses spaces in directory path (`lms lengkap/lms lengkap/`) — always quote paths in shell commands
