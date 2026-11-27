# IMARA-CARE API

The FastAPI backend for the IMARA-CARE hospital management MVP. It implements patient registration and search, duplicate checks, appointment booking, visit check-in and audited department handoffs, triage, department queues, and audit events.

See [IMPLEMENTED-FEATURES.md](./IMPLEMENTED-FEATURES.md) for the backend and frontend implementation summary, key API routes, verification results, and remaining limitations.

## Requirements

- Python 3.12 or later
- PostgreSQL 16 for a shared environment, or SQLite for the local demo

## Local setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.bootstrap
uvicorn app.main:app --reload
```

The bootstrap command applies Alembic migrations and seeds the configured facility and departments. The API and interactive docs are then available at [http://localhost:8000](http://localhost:8000) and [http://localhost:8000/docs](http://localhost:8000/docs). By default, the database is `imara-care.db` in the current directory.

## Deploy to Vercel

Import `Melissa9mpenzi/imara-care-api` as a new Vercel project with the repository root as the Root Directory. Vercel detects the FastAPI application from `index.py` and installs dependencies from `requirements.txt`.

Configure these Production environment variables before using the deployment:

```text
DATABASE_URL=<PostgreSQL connection string for the clinical database>
ENVIRONMENT=production
FRONTEND_ORIGIN=https://imara-care.vercel.app
AUTH_ISSUER=https://imara-care.vercel.app
AUTH_JWKS_URL=https://imara-care.vercel.app/api/auth/jwks
FACILITY_NAME=Imara Care Clinic
FACILITY_CODE=IM
```

Use a persistent hosted PostgreSQL database for `DATABASE_URL`; do not rely on the function's local SQLite file, which is not persistent. The service accepts `postgres://` and `postgresql://` URLs and normalizes them to the installed psycopg 3 SQLAlchemy driver. Apply schema migrations and seed the facility with `python -m app.bootstrap` as an explicit release step before serving API traffic; the API no longer creates tables or seeds data during startup. Use separate database variables for preview/staging and production, and keep the existing authentication tables in the `auth` schema intact when sharing the frontend's database. Production frontend builds use `https://imara-care-api.vercel.app/api/v1`; local development can override the API base with `NEXT_PUBLIC_API_URL`. The public `/api/v1/health` endpoint can be used to verify service availability.

For a production migration, add the production PostgreSQL connection string as the GitHub Actions repository secret `DATABASE_URL` (Settings → Secrets and variables → Actions). Back up the database, then run **Production database migration** from the repository's Actions tab and explicitly confirm the production run. The workflow applies Alembic migrations, seeds missing facility defaults, and checks for schema drift; it does not print the secret. Never put the connection string in source code or chat.

The following connection example is for the project's Docker database; for a standalone PostgreSQL Server, follow the setup below:

```text
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/imara_care
```

Install and start PostgreSQL Server; pgAdmin is only the management app and cannot host the database by itself. In pgAdmin, connect to the local server (usually `localhost`, port `5432`) using the username and password set during installation. Right-click **Databases** > **Create** > **Database** and name it `imara-caree`.

For this setup, use a URL like `postgresql+psycopg://postgres:URL_ENCODED_PASSWORD@localhost:5432/imara-caree` for `DATABASE_URL` in `backend/.env`. Replace the username and password with the values from your PostgreSQL Server installation. URL-encode special characters in the password.

Keep the existing SQLite file as a backup. From the `backend` directory, copy its clinical data into the new, empty PostgreSQL database:

```powershell
python -m app.migrate_sqlite_to_postgres
```

The migration creates the clinical tables and copies their records; it refuses to run if the destination database already contains tables. After a successful migration, the API uses PostgreSQL through `DATABASE_URL`. The separate `web/imara-care-auth.db` login database is not migrated by this command.

Set `FACILITY_NAME`, `FACILITY_CODE`, `FRONTEND_ORIGIN`, `AUTH_ISSUER`, and `AUTH_JWKS_URL` to configure the local facility, browser origin, and Better Auth token verification. Keep `AUTH_ISSUER` and `AUTH_JWKS_URL` aligned with the frontend's `BETTER_AUTH_URL`. Never commit `.env` files or real credentials.

For the shared local PostgreSQL service and Prisma-authored foundation tables, follow the PostgreSQL setup in `web/README.md`. The FastAPI models continue to manage clinical tables using SQLAlchemy; the Prisma schema owns the auth, tenant, role, permission, and audit foundation.

The API rejects clinical data access for platform administrators, facility administrators, medical directors, clinicians, and pharmacists until the signed-in staff account has completed authenticator-app MFA enrollment. MFA verification and recovery-code handling are provided by the frontend Better Auth service.

## Personal reminders and notifications

Staff can create private reminders from the dashboard. Reminders support one-time, daily, weekday, weekly, monthly, and every-N-days schedules, optional early alerts, and links to supported records. The API provides per-user reminder and notification lists and read/complete/cancel/snooze actions. Notification email, SMS, and browser-push delivery are not enabled.

## Help and support requests

Authenticated staff can submit technical/account support requests through `POST /api/v1/support/requests` and view their own requests through `GET /api/v1/support/requests`. Facility administrators can view facility requests and update their status through `PATCH /api/v1/support/requests/{request_id}`. Requests are facility-scoped and status changes are audited. Do not include patient identifiers or clinical information in support messages. The support form also links to `melissampenzi@gmail.com`; in-app requests are not automatically emailed.

The reminder processor can run as an always-on worker or be triggered by an external scheduler. A privileged facility administrator can read `GET /api/v1/operations/reminders`; the dashboard shows a warning when there has been no successful run within five minutes.

For the recommended always-on worker, build `Dockerfile.reminder-worker` as a background service from the backend repository. Set `DATABASE_URL` to the same persistent PostgreSQL database used by the API and `ENVIRONMENT=production`; start one worker instance in the same region as the database. Run `python -m app.bootstrap` as the release step before starting the API and worker. The worker does not need `CRON_SECRET`. This repository includes the worker image definition, but the hosting service, its environment variables, and its deployment have not been configured here.

Alternatively, an external scheduler can call `POST /api/v1/internal/jobs/reminders` with `Authorization: Bearer <CRON_SECRET>`. For that mode only, configure a randomly generated `CRON_SECRET` of at least 32 characters on the API. The endpoint creates a persisted run record and returns the processed count; requests are rejected when the secret is missing, too short, or incorrect. This endpoint does not configure a scheduler or guarantee it is called. Vercel Hobby cron timing may not meet a once-per-minute requirement. For local development, run the reminder scheduler in a separate terminal alongside the API:

```powershell
cd C:\Users\HP\Desktop\Imara-Care\backend
.\.venv\Scripts\Activate.ps1
python -m app.reminder_worker
```

The worker checks due reminder occurrences once per minute, stores the notification and occurrence update together, and uses database row locking where supported so multiple PostgreSQL workers do not claim the same occurrence. Both the worker and protected endpoint record job status, start/finish times, processed count, and a safe error class. With SQLite, run a single worker process. Notifications are polled by the web app; live event streaming, notification preferences, quiet hours, escalation, and delivery channels are not implemented yet.

## Billing workflow

Billing staff can create invoices with up to 50 itemized charge lines. The API calculates each line amount and invoice total from quantity and unit price, while retaining support for older description-and-total invoice requests. Invoice records can also hold bill-to contact information, payer/insurer references, optional service and due dates, and notes. Billing patient search is facility-scoped and includes active registered patients who do not yet have a department visit. Cashiers can record partial or full payments; overpayments remain rejected. The workspace provides search and status filters for the latest 100 invoices and supports invoice printing.

Each recorded payment receives a unique receipt number and can be printed as a payment receipt. Billing staff can create one manual claim for an insurance invoice and track draft, submitted, approved, denied, and paid states, including the insurer reference and notes. A claim can only be marked paid after an insurance payment is recorded against its invoice. This does not submit claims to insurers or automate remittance matching. Tax rules, refunds, and accounting exports are not implemented.

## Pharmacy, laboratory, and patient flow

Positive stock receipts require a batch number, expiry date of today or later, and receipt reference. The system shows unexpired eligible quantities separately and dispenses earliest-expiring eligible lots first; expired or untracked legacy quantities are not considered dispensable. Laboratory orders track sample collection, processing or rejection, result entry, and clinician review. Reception, clinicians, and nurses can hand an open visit off to Pharmacy or Laboratory with a required reason; the source queue entry is completed and a linked destination visit is queued. Handoffs are audit-logged, and nurses can only hand off visits from their assigned department.

These are workflow prototypes, not validated clinical decision support. Preserve local clinical policies and verify behavior with qualified staff before any real-world use.

## Synthetic demo data

For local workflow testing only, configure `ENVIRONMENT=development` and a local SQLite `DATABASE_URL`, then run:

```powershell
python -m scripts.seed_demo_data --confirm-demo-data
```

The script refuses production/test environments without SQLite and creates clearly labelled synthetic patient, queue, appointment, pharmacy, laboratory, billing, and theatre records. It is idempotent for its own seed records. Do not run it against a shared or production database, and do not enter real patient information in the demo environment.

## Tests

```powershell
python -m pytest -q
```

## API areas

- `GET /api/v1/health`, `GET /api/v1/facility`, `GET /api/v1/dashboard`
- `POST /api/v1/internal/jobs/reminders` (requires `Authorization: Bearer <CRON_SECRET>`), `GET /api/v1/operations/reminders` (privileged)
- `GET|POST /api/v1/patients`, `GET|PATCH|DELETE /api/v1/patients/{patient_id}`
- `POST /api/v1/patients/import` (multipart CSV/XLSX upload; use `?preview=true` to validate before creating new records)
- `GET|POST /api/v1/appointments`, `PATCH /api/v1/appointments/{appointment_id}`
- `POST /api/v1/visits/checkin`, `POST /api/v1/visits/{visit_id}/handoff`
- `GET /api/v1/queues`, `POST /api/v1/queues/{entry_id}/call`, `POST /api/v1/queues/call-next`
- `POST /api/v1/triage/{visit_id}`
- `GET|POST /api/v1/reminders`, `PATCH /api/v1/reminders/{reminder_id}`
- `GET /api/v1/notifications`, `POST /api/v1/notifications/read`, `POST /api/v1/notifications/{notification_id}/snooze`
- `GET|POST /api/v1/support/requests`, `PATCH /api/v1/support/requests/{request_id}`
- `GET /api/v1/audit`
- `POST /api/v1/billing/invoices/{invoice_id}/claims`, `PATCH /api/v1/billing/claims/{claim_id}`
- `POST /api/v1/pharmacy/stock/import` (multipart CSV/XLSX upload; use `?preview=true` before confirming matched-item restocks)

Spreadsheet imports accept `.csv` and `.xlsx` files up to 5 MB and 500 non-empty data rows. Patient imports create valid new records only; existing and repeated patients are reported as duplicates and are never overwritten. Pharmacy stock imports add quantities to matching items only after explicit confirmation, preserve existing prices and reorder levels, and require batch, expiry, and a unique receipt reference to prevent accidental repeat imports. Both workflows report invalid and duplicate rows without importing them.

## Important limitations

This is an early development/demo MVP. The API requires a Better Auth bearer token scoped to the configured facility and enforces MFA enrollment for sensitive staff roles. API endpoint permissions distinguish administrative, reception, records, clinical, nursing, and department roles; nurses and department heads are scoped to their assigned department. Alembic now owns clinical schema changes; the initial migration is guarded and additive for the inspected legacy schema, and startup never mutates the database. This is not a substitute for a hospital security assessment: social sign-in, passkeys, multi-facility routing, PostgreSQL row-level tenant isolation, production migration automation, and backup/restore drills are not implemented. Production backup and restore configuration has not been confirmed or tested. Billing, pharmacy, laboratory, and theatre workflows are prototypes and require clinical, operational, financial, and regulatory validation before real patient use. Do not use real patient information or expose the development API to the internet.
