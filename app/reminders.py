from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.models import (
    Facility,
    Notification,
    Reminder,
    ReminderOccurrence,
)
from app.reminder_schemas import (
    NotificationReadRequest,
    ReminderAction,
    ReminderCreate,
)


router = APIRouter(prefix="/api/v1", tags=["notifications and reminders"])


def _owner_id(request: Request) -> str:
    return request.state.staff_user["id"]


def _facility_id(db: Session) -> str:
    facility = db.scalar(select(Facility).where(Facility.code == settings.facility_code))
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")
    return facility.id


def _schedule_occurrences(
    db: Session,
    reminder: Reminder,
    offsets: list[int] | None = None,
) -> None:
    for offset in (reminder.alert_offsets if offsets is None else offsets):
        db.add(
            ReminderOccurrence(
                reminder_id=reminder.id,
                fire_at=reminder.due_at - timedelta(minutes=offset),
                alert_offset_minutes=offset,
            )
        )


def _reminder_summary(reminder: Reminder) -> dict:
    return {
        "id": reminder.id,
        "title": reminder.title,
        "note": reminder.note,
        "link_type": reminder.link_type,
        "link_id": reminder.link_id,
        "due_at": reminder.due_at,
        "timezone": reminder.timezone,
        "repeat_frequency": reminder.repeat_frequency,
        "repeat_interval": reminder.repeat_interval,
        "repeat_until": reminder.repeat_until,
        "alert_offsets": reminder.alert_offsets,
        "priority": reminder.priority,
        "status": reminder.status,
        "created_at": reminder.created_at,
    }


def _notification_summary(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "reminder_id": (
            notification.reminder_occurrence.reminder_id
            if notification.reminder_occurrence
            else None
        ),
        "type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "link_type": notification.link_type,
        "link_id": notification.link_id,
        "priority": notification.priority,
        "status": notification.status,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
    }


@router.get("/reminders")
def list_reminders(
    request: Request,
    status_filter: str = Query(default="active", alias="status", pattern="^(active|completed|all)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = select(Reminder).where(
        Reminder.facility_id == _facility_id(db),
        Reminder.owner_id == _owner_id(request),
    )
    if status_filter == "active":
        query = query.where(Reminder.status == "scheduled")
    elif status_filter == "completed":
        query = query.where(Reminder.status.in_(["completed", "cancelled"]))
    reminders = db.scalars(query.order_by(Reminder.due_at).limit(limit)).all()
    return [_reminder_summary(reminder) for reminder in reminders]


@router.post("/reminders", status_code=201)
def create_reminder(
    payload: ReminderCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    values = payload.model_dump(exclude={"due_at", "repeat_until"})
    reminder = Reminder(
        facility_id=_facility_id(db),
        owner_id=_owner_id(request),
        created_by=_owner_id(request),
        **values,
        due_at=payload.due_at.astimezone(timezone.utc),
        repeat_until=(
            payload.repeat_until.astimezone(timezone.utc) if payload.repeat_until else None
        ),
    )
    db.add(reminder)
    db.flush()
    _schedule_occurrences(db, reminder)
    db.commit()
    db.refresh(reminder)
    return _reminder_summary(reminder)


@router.patch("/reminders/{reminder_id}")
def update_reminder(
    reminder_id: str,
    payload: ReminderAction,
    request: Request,
    db: Session = Depends(get_db),
):
    reminder = db.scalar(
        select(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.facility_id == _facility_id(db),
            Reminder.owner_id == _owner_id(request),
        )
    )
    if reminder is None:
        raise HTTPException(status_code=404, detail="Reminder not found.")
    if reminder.status != "scheduled":
        raise HTTPException(status_code=409, detail="This reminder is no longer active.")

    if payload.action in {"done", "cancel"}:
        reminder.status = "completed" if payload.action == "done" else "cancelled"
        db.execute(
            update(ReminderOccurrence)
            .where(
                ReminderOccurrence.reminder_id == reminder.id,
                ReminderOccurrence.status == "pending",
            )
            .values(status="skipped")
        )
    else:
        snooze_until = payload.snooze_until.astimezone(timezone.utc)
        if snooze_until <= datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Snooze time must be in the future.")
        reminder.due_at = snooze_until
        db.execute(
            update(ReminderOccurrence)
            .where(
                ReminderOccurrence.reminder_id == reminder.id,
                ReminderOccurrence.status == "pending",
            )
            .values(status="skipped")
        )
        _schedule_occurrences(db, reminder, offsets=[0])

    db.commit()
    db.refresh(reminder)
    return _reminder_summary(reminder)


@router.get("/notifications")
def list_notifications(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    unread_only: bool = False,
    db: Session = Depends(get_db),
):
    facility_id = _facility_id(db)
    owner_id = _owner_id(request)
    now = datetime.now(timezone.utc)
    base = select(Notification).where(
        Notification.facility_id == facility_id,
        Notification.recipient_user_id == owner_id,
        Notification.status != "archived",
        (Notification.snoozed_until.is_(None) | (Notification.snoozed_until <= now)),
    )
    unread_count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.facility_id == facility_id,
            Notification.recipient_user_id == owner_id,
            Notification.status == "unread",
            (Notification.snoozed_until.is_(None) | (Notification.snoozed_until <= now)),
        )
    )
    if unread_only:
        base = base.where(Notification.status == "unread")
    items = db.scalars(
        base.options(
            joinedload(Notification.reminder_occurrence).joinedload(
                ReminderOccurrence.reminder
            )
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "items": [_notification_summary(item) for item in items],
        "unread_count": unread_count or 0,
    }


@router.post("/notifications/read")
def mark_notifications_read(
    payload: NotificationReadRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    query = update(Notification).where(
        Notification.facility_id == _facility_id(db),
        Notification.recipient_user_id == _owner_id(request),
        Notification.status == "unread",
    )
    if payload.notification_ids is not None:
        query = query.where(Notification.id.in_(payload.notification_ids))
    now = datetime.now(timezone.utc)
    result = db.execute(query.values(status="read", read_at=now))
    db.commit()
    return {"updated": result.rowcount}


@router.post("/notifications/{notification_id}/snooze")
def snooze_notification(
    notification_id: str,
    request: Request,
    snooze_until: datetime,
    db: Session = Depends(get_db),
):
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.facility_id == _facility_id(db),
            Notification.recipient_user_id == _owner_id(request),
            Notification.status == "unread",
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if snooze_until.tzinfo is None or snooze_until <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Snooze time must be in the future and include a timezone.")
    notification.snoozed_until = snooze_until.astimezone(timezone.utc)
    db.commit()
    return _notification_summary(notification)
