# MediRefill – Smart Pharmacy Reordering Platform

Responsive pharmacy reordering prototype for Company A's Kolkata/Howrah brief.

## Included flows
- Customer sign-in, family profiles, medicine reorder, prescription upload and order tracking.
- Email OTP sign-in for customer accounts (SMTP required); password sign-in remains for seeded demo accounts and staff.
- Tesseract OCR for prescription images and first PDF page. OCR results are structured as an **unverified draft** and displayed in the pharmacist queue.
- Pharmacist approve, reject with reason or request re-upload. Schedule H/H1 orders stay blocked until pharmacist approval; Schedule X/narcotic orders are blocked from online ordering.
- Stock-aware nearest eligible store routing from seeded sample data; operations CSV stock import.
- Refill reminder screen and operations dashboard with live inventory by store.
- Inventory quantities are deducted when a pharmacist approves an order; approval is blocked when the selected store does not have sufficient stock.
- Prescription files encrypted at rest using Fernet; CSRF protection on forms; role checks; access audit events.

## Local setup
1. Python 3.10+ and Tesseract OCR required. For PDFs, Poppler is also required.
2. `python -m venv .venv` and activate it.
3. `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`; set all secrets and SMTP settings. Generate an encryption key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
5. Export environment variables in your shell (or use a dotenv loader) and run `python -c "import app; app.init_db()"`.
6. Run `python app.py` and open `http://127.0.0.1:5000`.

## Demo credentials
- Customer: customer@medirefill.demo / Customer@123
- Pharmacist: pharmacist@medirefill.demo / Pharmacist@123
- Operations: ops@medirefill.demo / Ops@123

Email OTP is for customer accounts and requires SMTP variables. Password login is retained for reviewer convenience and staff demo accounts.

## Tests
Run `pytest -q`. GitHub Actions workflow is included. Tests cover password hashing, login/health route smoke checks, encryption, upload validation and OCR draft extraction.

## Repository
Public source repository: https://github.com/Dhanush47-cloud/MediRefill

## Deployment — PythonAnywhere
The current demo deployment is hosted on PythonAnywhere:

- **Live application:** https://dhanushban.pythonanywhere.com
- **Operations dashboard:** https://dhanushban.pythonanywhere.com/ops
- **Hosting:** PythonAnywhere (Flask web app)
- **Application directory:** `/home/DhanushBan/MediRefill`
- **WSGI entry point:** `app.py` is exposed as the WSGI application.
- **Database:** SQLite database stored in the project directory (`medirefill.db`).
- **Prescription storage:** Encrypted uploads are stored in the private `private_uploads/` directory.

### PythonAnywhere deployment notes
1. Upload or clone the project into the application directory.
2. Create and configure a virtual environment, then install dependencies from `requirements.txt`.
3. Configure the PythonAnywhere Web app to use the project's virtual environment and WSGI file.
4. Set `FLASK_SECRET_KEY` and `PRESCRIPTION_ENCRYPTION_KEY` in the WSGI configuration before importing the Flask application. Keep these values private and stable; changing the encryption key makes previously encrypted prescription files unreadable.
5. Ensure the SQLite database and private upload directory remain in persistent project storage. Do not delete them when updating application code.
6. After code or template changes, reload the web app from the PythonAnywhere **Web** tab.

**Hosting note:** This demo uses the PythonAnywhere free tier. Free-tier resource limits and renewal requirements may apply; sign in to the PythonAnywhere account regularly and check its current plan terms. The live URL is a demonstration deployment, not a production pharmacy service.

## Safety / limitations
- Tesseract OCR is real text recognition, but handwritten prescription accuracy is not clinically validated. Illegible or low-confidence text must be manually reviewed or re-uploaded. OCR never approves a medicine or dosage.
- No generic substitution, diagnosis, dosing advice or automated therapeutic recommendation is provided.
- Schedule X/narcotics are blocked; Schedule H/H1 approval is mandatory. H1 statutory register completeness and legal interpretation require qualified compliance review.
- The sample database contains synthetic demo data only. Production must use managed PostgreSQL, encrypted object storage/KMS, proper retention/deletion workflows, MFA, rate limiting, monitoring, backups, legal review and verified inventory reservation logic.
- Payments remain COD test mode; SMS/WhatsApp and live UPI are not connected.
