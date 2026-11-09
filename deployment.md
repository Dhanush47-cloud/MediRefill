# MediRefill – Deployment Guide

## Status
This repository includes a Render Blueprint and Dockerfile. A public deployment has not yet been created or verified. Do not describe a live URL as available until Render reports the service healthy.

## Local prerequisites
- Python 3.10+
- Tesseract OCR (`tesseract-ocr`); Poppler (`poppler-utils`) for PDF page conversion
- Git

## Setup
```bash
git clone https://github.com/Dhanush47-cloud/MediRefill.git
cd MediRefill
python -m venv .venv
```
Activate `.venv` (Windows PowerShell: `\.\.venv\Scripts\Activate.ps1`; macOS/Linux: `source .venv/bin/activate`), then:
```bash
pip install -r requirements.txt
cp .env.example .env
```
On Windows, use `Copy-Item .env.example .env` instead of `cp`.

Generate a Fernet key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Put that generated value in `PRESCRIPTION_ENCRYPTION_KEY` in your local `.env`. Also configure a long random `FLASK_SECRET_KEY`, independent `OTP_PEPPER`, and SMTP settings. Never commit `.env`.

Initialise and run:
```bash
python -c "import app; app.init_db()"
python app.py
```
Open `http://127.0.0.1:5000`.

## Render deployment
1. Push the repository to GitHub.
2. In Render, choose **New → Blueprint**, connect this repository and select `render.yaml`.
3. Configure `PRESCRIPTION_ENCRYPTION_KEY` and SMTP values; generated secrets are handled by the Blueprint.
4. Confirm persistent disk mount at `/var/data`.
5. Deploy and verify `/health`, sign-in, prescription upload, OCR draft, pharmacist decision and encrypted file retrieval.
6. Add a live URL to the TDD only after verification.

## Tests
Run `pytest -q`. GitHub Actions is configured to install Tesseract and Poppler and run the suite. The full suite has not yet been verified in this runtime.

## Security and production readiness
- CSRF protection is enabled; session cookies are HttpOnly and SameSite=Lax.
- Prescription files are encrypted with Fernet. Protect and back up the encryption key.
- Email OTP requires SMTP. Add staff MFA, provider-side abuse controls and rate limiting before production.
- Handwriting OCR accuracy is not clinically validated; every result is an unverified draft requiring pharmacist review.
- Prototype limitations include SQLite, seeded four-store data, COD test payment and no production stock reservation or regulatory certification.
- Use synthetic data only. Production requires managed database and object storage/KMS, TLS, malware scanning, retention controls, monitoring, backups and legal/compliance review.
