# FamilySide Backend

A FastAPI backend for the FamilySide mobile/web application. This repository provides API routes for user authentication, onboarding, admin dashboard, activities, events, gifts, and provider flows, backed by PostgreSQL and managed migrations with Alembic.

## Key Features
- RESTful API built with FastAPI
- PostgreSQL persistence (Docker-friendly)
- SQLAlchemy ORM models and Alembic migrations
- Authentication, admin dashboard, provider and family endpoints
- File upload handling and static `uploads/` mounting

## Tech Stack
- Python 3.10+
- FastAPI
- SQLAlchemy
- PostgreSQL
- Alembic
- Uvicorn

## Repository Layout
- `app/` - application package (API routers, models, schemas, services)
  - `api/v1/` - versioned API routers (admin, auth, family, provider, onboarding)
  - `models/` - SQLAlchemy data models
  - `schemas/` - Pydantic schemas
  - `db/` - DB session and initialization helpers
  - `core/` - configuration and utility helpers
- `alembic/` - Alembic migrations
- `uploads/` - runtime uploaded file storage (created automatically)
- `docker-compose.yml` - convenience compose file for a local Postgres
- `requirements.txt` - Python dependencies

## Environment variables
Create a `.env` file at the project root (or set system env vars). The application reads configuration from `app/core/config.py`. Common variables:

- `DATABASE_URL` — Postgres connection string (e.g. `postgresql+psycopg2://postgres:postgres123@localhost:5432/familyside`)
- `SECRET_KEY` — JWT secret
- `ALGORITHM` — JWT algorithm (default: `HS256`)
- `ACCESS_TOKEN_EXPIRE_DAYS` — number of days for access tokens (default: `7`)
- `RESET_TOKEN_EXPIRE_MINUTES` — reset token expiry in minutes (default: `15`)
- `GOOGLE_CLIENT_ID`, `APPLE_CLIENT_ID` — social auth client IDs (optional)
- Mail settings: `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_PORT`, `MAIL_SERVER`, `MAIL_STARTTLS`, `MAIL_SSL_TLS`, `MAIL_FROM_NAME`
- `base_url` — public base URL used when building full file URLs (optional)

Example `.env` snippet:

```
DATABASE_URL=postgresql+psycopg2://postgres:postgres123@localhost:5432/familyside
SECRET_KEY=supersecret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_DAYS=7
MAIL_USERNAME=you@example.com
MAIL_PASSWORD=secret
MAIL_FROM=you@example.com
MAIL_PORT=587
MAIL_SERVER=smtp.example.com
MAIL_STARTTLS=True
MAIL_SSL_TLS=False
base_url=http://localhost:8015/
```

## Local Development

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate    # or .venv\\Scripts\\activate on Windows
pip install -r requirements.txt
```

2. Start a local PostgreSQL (recommended using Docker Compose):

```bash
docker-compose up -d
```

3. Ensure the `DATABASE_URL` env var points to your DB and run Alembic migrations:

```bash
alembic upgrade heads
```

4. Start the FastAPI server:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8015
```

5. Open docs at: http://localhost:8015/docs

Notes:
- The server mounts `uploads/` at `/uploads` to serve uploaded assets. The folder is created automatically on startup.
- Many admin/provider endpoints accept `multipart/form-data` for file uploads.

## Running in Docker (Postgres only)
The included `docker-compose.yml` only provisions the Postgres DB. Use the local instructions above to run the Python app.

## Database Migrations (Alembic)
- Migration scripts are in the `alembic/versions/` folder.
- To create a new migration after model changes:

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade heads
```

## Contributing
- Fork the repository, create a feature branch, and submit a pull request.
- Follow the existing code style and add tests for new features where appropriate.