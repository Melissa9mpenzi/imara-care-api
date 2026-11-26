import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import JobRun
from app.reminder_worker import run_reminder_job


router = APIRouter(prefix="/api/v1", tags=["internal jobs"])
REMINDER_STALE_AFTER_SECONDS = 300


def _check_cron_authorization(authorization: str) -> None:
    if len(settings.cron_secret) < 32:
        raise HTTPException(
            status_code=503,
            detail="Scheduled reminder jobs are not securely configured.",
        )
    scheme, _, supplied_secret = authorization.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied_secret,
        settings.cron_secret,
    ):
        raise HTTPException(status_code=401, detail="Unauthorized.")


@router.post("/internal/jobs/reminders")
def trigger_reminder_job(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
):
    _check_cron_authorization(authorization)
    return run_reminder_job(db)


@router.get("/operations/reminders")
def reminder_job_status(db: Session = Depends(get_db)):
    latest = db.scalar(
        select(JobRun)
        .where(JobRun.name == "reminders")
        .order_by(JobRun.started_at.desc())
        .limit(1)
    )
    if latest is None:
        return {
            "last_run": None,
            "stale_after_seconds": REMINDER_STALE_AFTER_SECONDS,
            "stale": True,
        }

    now = datetime.now(timezone.utc)
    last_activity = latest.finished_at or latest.started_at
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)
    age_seconds = max(0, int((now - last_activity).total_seconds()))
    started_at = latest.started_at
    finished_at = latest.finished_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if finished_at is not None and finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    stale = (
        latest.status != "succeeded"
        or latest.finished_at is None
        or age_seconds > REMINDER_STALE_AFTER_SECONDS
    )
    return {
        "last_run": {
            "status": latest.status,
            "started_at": started_at,
            "finished_at": finished_at,
            "processed": latest.processed_count,
            "error": latest.error,
        },
        "stale_after_seconds": REMINDER_STALE_AFTER_SECONDS,
        "stale": stale,
    }
