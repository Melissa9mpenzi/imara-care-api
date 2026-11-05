import calendar
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models import Notification, Reminder, ReminderOccurrence


logger = logging.getLogger("imara.reminders")


def _next_due(reminder: Reminder) -> datetime | None:
    due_at = reminder.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    local_due = due_at.astimezone(ZoneInfo(reminder.timezone))
    frequency = reminder.repeat_frequency
    interval = reminder.repeat_interval

    if frequency == "daily":
        next_local = local_due + timedelta(days=interval)
    elif frequency == "weekdays":
        next_local = local_due
        remaining = interval
        while remaining:
            next_local += timedelta(days=1)
            if next_local.weekday() < 5:
                remaining -= 1
    elif frequency == "weekly":
        next_local = local_due + timedelta(weeks=interval)
    elif frequency == "custom":
        next_local = local_due + timedelta(days=interval)
    elif frequency == "monthly":
        month_index = local_due.month - 1 + interval
        year = local_due.year + month_index // 12
        month = month_index % 12 + 1
        day = min(local_due.day, calendar.monthrange(year, month)[1])
        next_local = local_due.replace(year=year, month=month, day=day)
    else:
        return None

    next_utc = next_local.astimezone(timezone.utc)
    if reminder.repeat_until is not None:
        repeat_until = reminder.repeat_until
        if repeat_until.tzinfo is None:
            repeat_until = repeat_until.replace(tzinfo=timezone.utc)
        if next_utc > repeat_until:
            return None
    return next_utc


def _add_occurrences(db: Session, reminder: Reminder) -> None:
    for offset in reminder.alert_offsets:
        db.add(
            ReminderOccurrence(
                reminder_id=reminder.id,
                fire_at=reminder.due_at - timedelta(minutes=offset),
                alert_offset_minutes=offset,
            )
        )


def process_due_occurrences(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    occurrences = db.scalars(
        select(ReminderOccurrence)
        .join(Reminder)
        .options(joinedload(ReminderOccurrence.reminder))
        .where(
            ReminderOccurrence.status == "pending",
            ReminderOccurrence.fire_at <= now,
            Reminder.status == "scheduled",
        )
        .order_by(ReminderOccurrence.fire_at, ReminderOccurrence.id)
        .limit(200)
        .with_for_update(skip_locked=True)
    ).all()

    processed = 0
    for occurrence in occurrences:
        reminder = occurrence.reminder
        occurrence.status = "fired"
        occurrence.fired_at = now
        db.add(
            Notification(
                facility_id=reminder.facility_id,
                recipient_user_id=reminder.owner_id,
                reminder_occurrence_id=occurrence.id,
                type="personal_reminder",
                title=reminder.title,
                body=reminder.note or "Your reminder is due.",
                link_type=reminder.link_type,
                link_id=reminder.link_id,
                priority=reminder.priority,
            )
        )
        processed += 1

        if occurrence.alert_offset_minutes == 0:
            next_due = _next_due(reminder)
            if next_due is not None:
                reminder.due_at = next_due
                _add_occurrences(db, reminder)
            elif reminder.repeat_frequency != "none":
                reminder.status = "completed"

    db.commit()
    return processed


def run_worker(poll_seconds: int = 60) -> None:
    logger.info("Reminder worker started; polling every %s seconds.", poll_seconds)
    while True:
        with SessionLocal() as db:
            processed = process_due_occurrences(db)
        if processed:
            logger.info("Delivered %s reminder notification(s).", processed)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
