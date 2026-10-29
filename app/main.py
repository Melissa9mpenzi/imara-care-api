from datetime import date, datetime, time, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import (
    Appointment,
    AuditEvent,
    Department,
    Facility,
    Patient,
    QueueEntry,
    TriageRecord,
    Visit,
)
from app.schemas import (
    AppointmentCreate,
    AppointmentStatusUpdate,
    CheckInCreate,
    PatientCreate,
    PatientRead,
    TriageCreate,
)


DEFAULT_DEPARTMENTS = [
    ("General Outpatient", "OPD", "consultation", "OPD"),
    ("Dental", "DEN", "consultation", "DEN"),
    ("ENT", "ENT", "consultation", "ENT"),
    ("Gynaecology", "GYN", "consultation", "GYN"),
    ("Antenatal", "ANC", "consultation", "ANC"),
    ("Ophthalmology", "OPH", "consultation", "OPH"),
    ("Physiotherapy", "PHY", "consultation", "PHY"),
    ("Laboratory", "LAB", "laboratory", "LAB"),
    ("Pharmacy", "PHARM", "pharmacy", "PH"),
    ("Theatre", "THR", "procedure", "THR"),
]

OPEN_VISIT_STATUSES = {
    "checked_in",
    "in_triage",
    "waiting",
    "in_consultation",
    "awaiting_lab",
    "awaiting_pharmacy",
    "awaiting_billing",
}


def audit(
    db: Session,
    facility_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
    actor: str = "Front desk",
) -> None:
    db.add(
        AuditEvent(
            facility_id=facility_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        facility = db.scalar(select(Facility).where(Facility.code == settings.facility_code))
        if facility is None:
            facility = Facility(
                name=settings.facility_name,
                code=settings.facility_code,
                currency="UGX",
                timezone="Africa/Kampala",
            )
            db.add(facility)
            db.flush()
        for name, code, department_type, prefix in DEFAULT_DEPARTMENTS:
            exists = db.scalar(
                select(Department.id).where(
                    Department.facility_id == facility.id,
                    Department.code == code,
                )
            )
            if not exists:
                db.add(
                    Department(
                        facility_id=facility.id,
                        name=name,
                        code=code,
                        type=department_type,
                        queue_prefix=prefix,
                    )
                )
        db.commit()


app = FastAPI(
    title=settings.app_name,
    description="Local MVP API for patient registration, appointments, check-in, triage, and queues.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    initialize_database()


def get_facility(db: Session) -> Facility:
    facility = db.scalar(select(Facility).where(Facility.code == settings.facility_code))
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")
    return facility


def patient_summary(patient: Patient) -> dict:
    return {
        "id": patient.id,
        "patient_number": patient.patient_number,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "other_names": patient.other_names,
        "full_name": " ".join(
            part for part in (patient.first_name, patient.other_names, patient.last_name) if part
        ),
        "sex": patient.sex,
        "date_of_birth": (
            patient.date_of_birth.isoformat() if patient.date_of_birth else None
        ),
        "estimated_age": patient.estimated_age,
        "phone": patient.phone,
        "email": patient.email,
        "address": patient.address,
        "usual_payment_method": patient.usual_payment_method,
        "allergies": patient.allergies,
        "sms_consent": patient.sms_consent,
        "created_at": patient.created_at.isoformat() if patient.created_at else None,
    }


def queue_summary(entry: QueueEntry) -> dict:
    visit = entry.visit
    patient = visit.patient
    return {
        "id": entry.id,
        "queue_number": entry.queue_number,
        "priority": entry.priority,
        "status": entry.status,
        "arrived_at": entry.arrived_at,
        "called_at": entry.called_at,
        "visit_id": visit.id,
        "visit_number": visit.visit_number,
        "visit_status": visit.status,
        "reason": visit.reason,
        "patient": patient_summary(patient),
        "department": {
            "id": visit.department.id,
            "name": visit.department.name,
            "code": visit.department.code,
        },
        "triage": (
            {
                "temperature": visit.triage.temperature,
                "pulse": visit.triage.pulse,
                "respiratory_rate": visit.triage.respiratory_rate,
                "systolic": visit.triage.systolic,
                "diastolic": visit.triage.diastolic,
                "spo2": visit.triage.spo2,
                "weight": visit.triage.weight,
                "height": visit.triage.height,
                "bmi": visit.triage.bmi,
                "pain_score": visit.triage.pain_score,
                "priority": visit.triage.priority,
            }
            if visit.triage
            else None
        ),
    }


def require_department(
    db: Session,
    facility_id: str,
    department_id: str,
    lock: bool = False,
) -> Department:
    query = select(Department).where(
        Department.id == department_id,
        Department.facility_id == facility_id,
        Department.active.is_(True),
    )
    if lock:
        query = query.with_for_update()
    department = db.scalar(query)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found.")
    return department


def call_entry(db: Session, facility_id: str, entry_id: str, staff_name: str) -> dict:
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(QueueEntry)
        .where(
            QueueEntry.id == entry_id,
            QueueEntry.facility_id == facility_id,
            QueueEntry.status == "waiting",
        )
        .values(status="in_service", called_at=now, called_by=staff_name)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This patient is no longer waiting.")

    entry = db.scalar(
        select(QueueEntry)
        .options(
            joinedload(QueueEntry.visit).joinedload(Visit.patient),
            joinedload(QueueEntry.visit).joinedload(Visit.department),
            joinedload(QueueEntry.visit).joinedload(Visit.triage),
        )
        .where(QueueEntry.id == entry_id, QueueEntry.facility_id == facility_id)
    )
    if entry is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Queue entry not found.")
    entry.visit.status = "in_consultation"
    audit(
        db,
        facility_id,
        "queue.patient_called",
        "queue_entry",
        entry.id,
        {"staff_name": staff_name},
        actor=staff_name,
    )
    db.commit()
    db.refresh(entry)
    return queue_summary(entry)


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/v1/facility")
def read_facility(db: Session = Depends(get_db)):
    facility = get_facility(db)
    departments = db.scalars(
        select(Department)
        .where(Department.facility_id == facility.id, Department.active.is_(True))
        .order_by(Department.name)
    ).all()
    return {
        "id": facility.id,
        "name": facility.name,
        "code": facility.code,
        "currency": facility.currency,
        "timezone": facility.timezone,
        "departments": [
            {"id": item.id, "name": item.name, "code": item.code, "type": item.type}
            for item in departments
        ],
    }


@app.get("/api/v1/dashboard")
def read_dashboard(db: Session = Depends(get_db)):
    facility = get_facility(db)
    today = date.today()
    today_start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    today_end = today_start + timedelta(days=1)
    patients_today = db.scalar(
        select(func.count(Patient.id)).where(
            Patient.facility_id == facility.id,
            Patient.created_at >= today_start,
            Patient.created_at < today_end,
        )
    )
    visits_today = db.scalar(
        select(func.count(Visit.id)).where(
            Visit.facility_id == facility.id,
            Visit.visit_date >= today_start,
            Visit.visit_date < today_end,
        )
    )
    waiting_count = db.scalar(
        select(func.count(QueueEntry.id)).where(
            QueueEntry.facility_id == facility.id,
            QueueEntry.queue_date == today,
            QueueEntry.status == "waiting",
        )
    )
    appointments_today = db.scalar(
        select(func.count(Appointment.id)).where(
            Appointment.facility_id == facility.id,
            Appointment.starts_at >= today_start,
            Appointment.starts_at < today_end,
            Appointment.status.in_(["booked", "confirmed"]),
        )
    )
    departments = db.scalars(
        select(Department).where(
            Department.facility_id == facility.id,
            Department.active.is_(True),
        ).order_by(Department.name)
    ).all()
    return {
        "facility_name": facility.name,
        "date": today.isoformat(),
        "stats": {
            "patients_today": patients_today or 0,
            "visits_today": visits_today or 0,
            "waiting_now": waiting_count or 0,
            "appointments_today": appointments_today or 0,
        },
        "departments": [
            {
                "id": department.id,
                "name": department.name,
                "code": department.code,
                "waiting": db.scalar(
                    select(func.count(QueueEntry.id)).where(
                        QueueEntry.facility_id == facility.id,
                        QueueEntry.department_id == department.id,
                        QueueEntry.queue_date == today,
                        QueueEntry.status == "waiting",
                    )
                )
                or 0,
            }
            for department in departments
        ],
    }


@app.get("/api/v1/patients", response_model=list[PatientRead])
def search_patients(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    query = select(Patient).where(
        Patient.facility_id == facility.id,
        Patient.status == "active",
    )
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            or_(
                Patient.patient_number.ilike(term),
                Patient.first_name.ilike(term),
                Patient.last_name.ilike(term),
                Patient.other_names.ilike(term),
                Patient.phone.ilike(term),
                Patient.national_id.ilike(term),
            )
        )
    return db.scalars(
        query.order_by(Patient.created_at.desc()).offset(offset).limit(limit)
    ).all()


@app.post("/api/v1/patients", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    facility = db.scalar(
        select(Facility)
        .where(Facility.code == settings.facility_code)
        .with_for_update()
    )
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")
    duplicate_query = select(Patient).where(
        Patient.facility_id == facility.id,
        Patient.status == "active",
    )
    duplicate_checks = []
    if payload.phone:
        duplicate_checks.append(Patient.phone == payload.phone)
    if payload.date_of_birth:
        duplicate_checks.append(
            (func.lower(Patient.first_name) == payload.first_name.lower())
            & (func.lower(Patient.last_name) == payload.last_name.lower())
            & (Patient.date_of_birth == payload.date_of_birth)
        )
    if duplicate_checks:
        match = db.scalar(duplicate_query.where(or_(*duplicate_checks)).limit(1))
        if match:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "possible_duplicate",
                    "message": "A patient with the same phone number or name and date of birth already exists.",
                    "patient": patient_summary(match),
                },
            )

    sequence = facility.next_patient_number
    facility.next_patient_number += 1
    patient = Patient(
        facility_id=facility.id,
        patient_number=f"{facility.code}-{date.today().year}-{sequence:06d}",
        **payload.model_dump(),
    )
    db.add(patient)
    db.flush()
    audit(
        db,
        facility.id,
        "patient.created",
        "patient",
        patient.id,
        {"patient_number": patient.patient_number},
    )
    db.commit()
    db.refresh(patient)
    return patient


@app.get("/api/v1/patients/{patient_id}")
def read_patient(patient_id: str, db: Session = Depends(get_db)):
    facility = get_facility(db)
    patient = db.scalar(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.facility_id == facility.id,
            Patient.status == "active",
        )
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    visits = db.scalars(
        select(Visit)
        .options(joinedload(Visit.department), joinedload(Visit.queue_entry))
        .where(Visit.facility_id == facility.id, Visit.patient_id == patient.id)
        .order_by(Visit.visit_date.desc())
        .limit(20)
    ).all()
    return {
        "patient": patient_summary(patient),
        "visits": [
            {
                "id": visit.id,
                "visit_number": visit.visit_number,
                "visit_date": visit.visit_date,
                "status": visit.status,
                "reason": visit.reason,
                "department": visit.department.name,
                "queue_number": visit.queue_entry.queue_number if visit.queue_entry else None,
            }
            for visit in visits
        ],
    }


@app.get("/api/v1/appointments")
def list_appointments(
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    start_date = start or date.today()
    end_date = end or (start_date + timedelta(days=7))
    start_at = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    appointments = db.scalars(
        select(Appointment)
        .options(joinedload(Appointment.patient), joinedload(Appointment.department))
        .where(
            Appointment.facility_id == facility.id,
            Appointment.starts_at >= start_at,
            Appointment.starts_at < end_at,
        )
        .order_by(Appointment.starts_at)
        .limit(limit)
    ).all()
    return [
        {
            "id": item.id,
            "starts_at": item.starts_at,
            "ends_at": item.ends_at,
            "appointment_type": item.appointment_type,
            "clinician": item.clinician,
            "reason": item.reason,
            "notes": item.notes,
            "status": item.status,
            "patient": patient_summary(item.patient),
            "department": {"id": item.department.id, "name": item.department.name},
        }
        for item in appointments
    ]


@app.post("/api/v1/appointments", status_code=status.HTTP_201_CREATED)
def create_appointment(payload: AppointmentCreate, db: Session = Depends(get_db)):
    facility = get_facility(db)
    patient = db.scalar(
        select(Patient).where(
            Patient.id == payload.patient_id,
            Patient.facility_id == facility.id,
            Patient.status == "active",
        )
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    department = require_department(db, facility.id, payload.department_id)

    conflicts = select(Appointment.id).where(
        Appointment.facility_id == facility.id,
        Appointment.department_id == department.id,
        Appointment.status.in_(["booked", "confirmed"]),
        Appointment.starts_at < payload.ends_at,
        Appointment.ends_at > payload.starts_at,
    )
    if payload.clinician:
        conflicts = conflicts.where(Appointment.clinician == payload.clinician)
    if db.scalar(conflicts.limit(1)):
        raise HTTPException(status_code=409, detail="This appointment time is already booked.")

    appointment = Appointment(facility_id=facility.id, **payload.model_dump())
    db.add(appointment)
    db.flush()
    audit(
        db,
        facility.id,
        "appointment.created",
        "appointment",
        appointment.id,
        {"patient_id": patient.id, "department": department.code},
    )
    db.commit()
    return {
        "id": appointment.id,
        "status": appointment.status,
        "starts_at": appointment.starts_at,
        "ends_at": appointment.ends_at,
    }


@app.patch("/api/v1/appointments/{appointment_id}")
def update_appointment(
    appointment_id: str,
    payload: AppointmentStatusUpdate,
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    appointment = db.scalar(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.facility_id == facility.id,
        )
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found.")
    if appointment.status in {"cancelled", "no_show", "completed"}:
        raise HTTPException(status_code=409, detail="This appointment can no longer be changed.")
    if payload.status == "cancelled" and not (payload.cancellation_reason or "").strip():
        raise HTTPException(status_code=422, detail="A cancellation reason is required.")
    appointment.status = payload.status
    appointment.cancellation_reason = payload.cancellation_reason
    audit(
        db,
        facility.id,
        f"appointment.{payload.status}",
        "appointment",
        appointment.id,
        {"reason": payload.cancellation_reason},
    )
    db.commit()
    return {"id": appointment.id, "status": appointment.status}


@app.post("/api/v1/visits/checkin", status_code=status.HTTP_201_CREATED)
def check_in(payload: CheckInCreate, db: Session = Depends(get_db)):
    facility = db.scalar(
        select(Facility)
        .where(Facility.code == settings.facility_code)
        .with_for_update()
    )
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")
    patient = db.scalar(
        select(Patient).where(
            Patient.id == payload.patient_id,
            Patient.facility_id == facility.id,
            Patient.status == "active",
        )
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    department = require_department(db, facility.id, payload.department_id, lock=True)
    active_visit = db.scalar(
        select(Visit.id).where(
            Visit.facility_id == facility.id,
            Visit.patient_id == patient.id,
            Visit.department_id == department.id,
            Visit.status.in_(OPEN_VISIT_STATUSES),
        )
    )
    if active_visit:
        raise HTTPException(status_code=409, detail="This patient already has an open visit in this department.")

    today = date.today()
    day_start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    visits_today = db.scalar(
        select(func.count(Visit.id)).where(
            Visit.facility_id == facility.id,
            Visit.visit_date >= day_start,
        )
    ) or 0
    visit = Visit(
        facility_id=facility.id,
        patient_id=patient.id,
        department_id=department.id,
        visit_number=f"V-{today:%Y%m%d}-{visits_today + 1:04d}",
        reason=payload.reason,
        expected_payment_method=payload.expected_payment_method,
        status="waiting",
    )
    db.add(visit)
    db.flush()

    queue_count = db.scalar(
        select(func.count(QueueEntry.id)).where(
            QueueEntry.facility_id == facility.id,
            QueueEntry.department_id == department.id,
            QueueEntry.queue_date == today,
        )
    ) or 0
    entry = QueueEntry(
        facility_id=facility.id,
        visit_id=visit.id,
        department_id=department.id,
        queue_number=f"{department.queue_prefix}-{queue_count + 1:03d}",
        queue_date=today,
        priority=payload.priority,
    )
    db.add(entry)
    db.flush()
    audit(
        db,
        facility.id,
        "visit.checked_in",
        "visit",
        visit.id,
        {"department": department.code, "queue_number": entry.queue_number},
    )
    db.commit()
    db.refresh(entry)
    return queue_summary(entry)


@app.get("/api/v1/queues")
def list_queues(
    department_id: str | None = None,
    status_filter: str = Query(default="waiting", alias="status"),
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    query = (
        select(QueueEntry)
        .options(
            joinedload(QueueEntry.visit).joinedload(Visit.patient),
            joinedload(QueueEntry.visit).joinedload(Visit.department),
            joinedload(QueueEntry.visit).joinedload(Visit.triage),
        )
        .where(
            QueueEntry.facility_id == facility.id,
            QueueEntry.queue_date == date.today(),
        )
    )
    if status_filter != "all":
        query = query.where(QueueEntry.status == status_filter)
    if department_id:
        require_department(db, facility.id, department_id)
        query = query.where(QueueEntry.department_id == department_id)
    priority_order = case(
        (QueueEntry.priority == "emergency", 0),
        (QueueEntry.priority == "urgent", 1),
        else_=2,
    )
    entries = db.scalars(query.order_by(priority_order, QueueEntry.arrived_at)).all()
    return [queue_summary(item) for item in entries]


@app.post("/api/v1/queues/{entry_id}/call")
def call_queue_entry(
    entry_id: str,
    staff_name: str = Query(default="Triage Nurse", max_length=120),
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    exists = db.scalar(
        select(QueueEntry.id).where(
            QueueEntry.id == entry_id,
            QueueEntry.facility_id == facility.id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Queue entry not found.")
    return call_entry(db, facility.id, entry_id, staff_name)


@app.post("/api/v1/queues/call-next")
def call_next_patient(
    department_id: str,
    staff_name: str = Query(default="Triage Nurse", max_length=120),
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    require_department(db, facility.id, department_id)
    priority_order = case(
        (QueueEntry.priority == "emergency", 0),
        (QueueEntry.priority == "urgent", 1),
        else_=2,
    )
    entry_id = db.scalar(
        select(QueueEntry.id)
        .where(
            QueueEntry.facility_id == facility.id,
            QueueEntry.department_id == department_id,
            QueueEntry.queue_date == date.today(),
            QueueEntry.status == "waiting",
        )
        .order_by(priority_order, QueueEntry.arrived_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if entry_id is None:
        raise HTTPException(status_code=404, detail="No patients are waiting in this department.")
    return call_entry(db, facility.id, entry_id, staff_name)


@app.post("/api/v1/triage/{visit_id}")
def record_triage(visit_id: str, payload: TriageCreate, db: Session = Depends(get_db)):
    facility = get_facility(db)
    visit = db.scalar(
        select(Visit)
        .options(joinedload(Visit.patient), joinedload(Visit.department))
        .where(Visit.id == visit_id, Visit.facility_id == facility.id)
    )
    if visit is None:
        raise HTTPException(status_code=404, detail="Visit not found.")
    if visit.status not in OPEN_VISIT_STATUSES:
        raise HTTPException(status_code=409, detail="Triage can only be recorded for an open visit.")
    data = payload.model_dump(exclude={"recorded_by", "priority"})
    height_m = (payload.height / 100) if payload.height else None
    bmi = round(payload.weight / (height_m * height_m), 1) if payload.weight and height_m else None
    if visit.triage is None:
        record = TriageRecord(
            facility_id=facility.id,
            visit_id=visit.id,
            recorded_by=payload.recorded_by,
            **data,
        )
        db.add(record)
    else:
        record = visit.triage
        for key, value in data.items():
            setattr(record, key, value)
        record.recorded_by = payload.recorded_by
    record.priority = payload.priority
    record.bmi = bmi
    visit.status = "waiting"
    queue_entry = db.scalar(
        select(QueueEntry).where(
            QueueEntry.facility_id == facility.id,
            QueueEntry.visit_id == visit.id,
        )
    )
    if queue_entry:
        queue_entry.priority = payload.priority
    audit(
        db,
        facility.id,
        "triage.recorded",
        "visit",
        visit.id,
        {"priority": payload.priority, "bmi": bmi},
        actor=payload.recorded_by,
    )
    db.commit()
    return {
        "visit_id": visit.id,
        "priority": record.priority,
        "bmi": record.bmi,
        "recorded_by": record.recorded_by,
    }


@app.get("/api/v1/audit")
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    facility = get_facility(db)
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.facility_id == facility.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": event.id,
            "actor": event.actor,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "details": event.details,
            "created_at": event.created_at,
        }
        for event in events
    ]
