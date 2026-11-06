# IMARA-CARE API

The FastAPI backend for the IMARA-CARE hospital management MVP. It implements patient registration and search, duplicate checks, appointment booking, visit check-in, triage, department queues, and audit events.

## Requirements

- Python 3.12 or later
- PostgreSQL 16 for a shared environment, or SQLite for the local demo

## Local setup (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

The API and interactive docs are available at [http://localhost:8000](http://localhost:8000) and [http://localhost:8000/docs](http://localhost:8000/docs). By default, the API creates `imara-care.db` in the current directory and seeds the configured facility and its departments.

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

Use a persistent hosted PostgreSQL database for `DATABASE_URL`; do not rely on the function's local SQLite file, which is not persistent. The service creates its clinical tables and initial facility/departments on startup. Keep the existing authentication tables in the `auth` schema intact when sharing the frontend's database. Once deployed, set the frontend project's `NEXT_PUBLIC_API_URL` to the backend deployment URL followed by `/api/v1` and redeploy the frontend. The public `/api/v1/health` endpoint can be used to verify service availability.

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

Run the reminder scheduler in a separate terminal alongside the API:

```powershell
cd C:\Users\HP\Desktop\Imara-Care\backend
.\.venv\Scripts\Activate.ps1
python -m app.reminder_worker
```

The worker checks due reminder occurrences once per minute, stores the notification and occurrence update together, and uses database row locking where supported so multiple PostgreSQL workers do not claim the same occurrence. With SQLite, run a single worker process. Notifications are polled by the web app; live event streaming, notification preferences, quiet hours, escalation, and delivery channels are not implemented yet.

## Tests

```powershell
python -m pytest -q
```

## API areas

- `GET /api/v1/health`, `GET /api/v1/facility`, `GET /api/v1/dashboard`
- `GET|POST /api/v1/patients`, `GET|PATCH|DELETE /api/v1/patients/{patient_id}`
- `GET|POST /api/v1/appointments`, `PATCH /api/v1/appointments/{appointment_id}`
- `POST /api/v1/visits/checkin`
- `GET /api/v1/queues`, `POST /api/v1/queues/{entry_id}/call`, `POST /api/v1/queues/call-next`
- `POST /api/v1/triage/{visit_id}`
- `GET|POST /api/v1/reminders`, `PATCH /api/v1/reminders/{reminder_id}`
- `GET /api/v1/notifications`, `POST /api/v1/notifications/read`, `POST /api/v1/notifications/{notification_id}/snooze`
- `GET /api/v1/audit`

## Important limitations

This is an early development/demo MVP. The API requires a Better Auth bearer token scoped to the configured facility and enforces MFA enrollment for sensitive staff roles. Fine-grained role-based endpoint permissions, social sign-in, passkeys, multi-facility routing, PostgreSQL row-level tenant isolation, database migrations, and the remaining clinical, laboratory, pharmacy, theatre, and billing workflows are not implemented. Do not use real patient information or expose the development API to the internet.
