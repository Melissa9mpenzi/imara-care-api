from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="UGX", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Kampala", nullable=False)
    next_patient_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    departments: Mapped[list["Department"]] = relationship(back_populates="facility")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("facility_id", "code", name="uq_department_facility_code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    type: Mapped[str] = mapped_column(String(24), default="consultation", nullable=False)
    queue_prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    facility: Mapped[Facility] = relationship(back_populates="departments")


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        UniqueConstraint("facility_id", "patient_number", name="uq_patient_facility_number"),
        Index("ix_patient_facility_phone", "facility_id", "phone"),
        Index("ix_patient_facility_name", "facility_id", "last_name", "first_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    patient_number: Mapped[str] = mapped_column(String(32), nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    other_names: Mapped[str | None] = mapped_column(String(120))
    sex: Mapped[str] = mapped_column(String(24), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    estimated_age: Mapped[int | None] = mapped_column(Integer)
    phone: Mapped[str | None] = mapped_column(String(32))
    alt_phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    national_id: Mapped[str | None] = mapped_column(String(64))
    address: Mapped[str | None] = mapped_column(String(240))
    next_of_kin_name: Mapped[str | None] = mapped_column(String(160))
    next_of_kin_relationship: Mapped[str | None] = mapped_column(String(80))
    next_of_kin_phone: Mapped[str | None] = mapped_column(String(32))
    usual_payment_method: Mapped[str] = mapped_column(String(24), default="cash", nullable=False)
    allergies: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    sms_consent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    visits: Mapped[list["Visit"]] = relationship(back_populates="patient")


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        Index("ix_appointment_facility_start", "facility_id", "starts_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    appointment_type: Mapped[str] = mapped_column(String(32), default="new", nullable=False)
    clinician: Mapped[str | None] = mapped_column(String(120))
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="booked", nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    patient: Mapped[Patient] = relationship()
    department: Mapped[Department] = relationship()


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        UniqueConstraint("facility_id", "visit_number", name="uq_visit_facility_number"),
        Index("ix_visit_facility_status", "facility_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.id"), index=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    visit_number: Mapped[str] = mapped_column(String(32), nullable=False)
    visit_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)
    expected_payment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(28), default="waiting", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    patient: Mapped[Patient] = relationship(back_populates="visits")
    department: Mapped[Department] = relationship()
    queue_entry: Mapped["QueueEntry | None"] = relationship(back_populates="visit", uselist=False)
    triage: Mapped["TriageRecord | None"] = relationship(back_populates="visit", uselist=False)


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    __table_args__ = (
        UniqueConstraint("facility_id", "department_id", "queue_number", "queue_date", name="uq_queue_daily_number"),
        Index("ix_queue_waiting", "facility_id", "department_id", "status", "priority", "arrived_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[str] = mapped_column(ForeignKey("visits.id"), unique=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("departments.id"), index=True)
    queue_number: Mapped[str] = mapped_column(String(20), nullable=False)
    queue_date: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="routine", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="waiting", nullable=False)
    arrived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    called_by: Mapped[str | None] = mapped_column(String(120))

    visit: Mapped[Visit] = relationship(back_populates="queue_entry")


class TriageRecord(Base):
    __tablename__ = "triage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    visit_id: Mapped[str] = mapped_column(ForeignKey("visits.id"), unique=True)
    temperature: Mapped[float | None] = mapped_column(Float)
    pulse: Mapped[int | None] = mapped_column(Integer)
    respiratory_rate: Mapped[int | None] = mapped_column(Integer)
    systolic: Mapped[int | None] = mapped_column(Integer)
    diastolic: Mapped[int | None] = mapped_column(Integer)
    spo2: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    bmi: Mapped[float | None] = mapped_column(Float)
    pain_score: Mapped[int | None] = mapped_column(Integer)
    blood_sugar: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(16), default="routine", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    visit: Mapped[Visit] = relationship(back_populates="triage")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminder_owner_status_due", "owner_id", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    link_type: Mapped[str | None] = mapped_column(String(32))
    link_id: Mapped[str | None] = mapped_column(String(128))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    repeat_frequency: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    repeat_interval: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    repeat_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alert_offsets: Mapped[list[int]] = mapped_column(JSON, default=lambda: [0], nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    occurrences: Mapped[list["ReminderOccurrence"]] = relationship(
        back_populates="reminder", cascade="all, delete-orphan"
    )


class ReminderOccurrence(Base):
    __tablename__ = "reminder_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "reminder_id", "fire_at", "alert_offset_minutes",
            name="uq_reminder_occurrence_fire_offset",
        ),
        Index("ix_reminder_occurrence_pending", "status", "fire_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reminder_id: Mapped[str] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), index=True
    )
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alert_offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reminder: Mapped[Reminder] = relationship(back_populates="occurrences")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notification_recipient_status_created", "recipient_user_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    recipient_user_id: Mapped[str] = mapped_column(String(128), index=True)
    reminder_occurrence_id: Mapped[str | None] = mapped_column(
        ForeignKey("reminder_occurrences.id", ondelete="SET NULL"), unique=True
    )
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    link_type: Mapped[str | None] = mapped_column(String(32))
    link_id: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[str] = mapped_column(String(16), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="unread", nullable=False)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    reminder_occurrence: Mapped[ReminderOccurrence | None] = relationship()
