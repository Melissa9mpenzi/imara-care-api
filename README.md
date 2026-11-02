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

Set `DATABASE_URL` in `.env` to use PostgreSQL:

```text
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/imara_care
```

Set `FACILITY_NAME`, `FACILITY_CODE`, `FRONTEND_ORIGIN`, `AUTH_ISSUER`, and `AUTH_JWKS_URL` to configure the local facility, browser origin, and Better Auth token verification. Keep `AUTH_ISSUER` and `AUTH_JWKS_URL` aligned with the frontend's `BETTER_AUTH_URL`. Never commit `.env` files or real credentials.

The API rejects clinical data access for platform administrators, facility administrators, medical directors, clinicians, and pharmacists until the signed-in staff account has completed authenticator-app MFA enrollment. MFA verification and recovery-code handling are provided by the frontend Better Auth service.

## Tests

```powershell
python -m pytest -q
```

## API areas

- `GET /api/v1/health`, `GET /api/v1/facility`, `GET /api/v1/dashboard`
- `GET|POST /api/v1/patients`, `GET /api/v1/patients/{patient_id}`
- `GET|POST /api/v1/appointments`, `PATCH /api/v1/appointments/{appointment_id}`
- `POST /api/v1/visits/checkin`
- `GET /api/v1/queues`, `POST /api/v1/queues/{entry_id}/call`, `POST /api/v1/queues/call-next`
- `POST /api/v1/triage/{visit_id}`
- `GET /api/v1/audit`

## Important limitations

This is an early development/demo MVP. The API requires a Better Auth bearer token scoped to the configured facility and enforces MFA enrollment for sensitive staff roles. Fine-grained role-based endpoint permissions, social sign-in, passkeys, multi-facility routing, PostgreSQL row-level tenant isolation, database migrations, and the remaining clinical, laboratory, pharmacy, theatre, and billing workflows are not implemented. Do not use real patient information or expose the development API to the internet.
