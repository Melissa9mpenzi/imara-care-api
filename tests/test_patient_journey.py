from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import build_engine, get_db
from app import main
from app import security
from app.config import settings
from app.models import Notification, Reminder, ReminderOccurrence
from app.reminder_worker import process_due_occurrences


@pytest.mark.parametrize(
    ("database_url", "expected_driver"),
    [
        ("postgres://user:password@localhost/db", "postgresql+psycopg"),
        ("postgresql://user:password@localhost/db", "postgresql+psycopg"),
        ("postgresql+psycopg://user:password@localhost/db", "postgresql+psycopg"),
        ("sqlite:///:memory:", "sqlite"),
    ],
)
def test_build_engine_supports_postgres_connection_schemes(
    database_url: str,
    expected_driver: str,
):
    test_engine = build_engine(database_url)
    try:
        assert test_engine.url.drivername == expected_driver
    finally:
        test_engine.dispose()


@pytest.fixture
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    test_session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        with test_session_factory() as session:
            yield session

    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main, "SessionLocal", test_session_factory)
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {"sub": "test-staff", "facilityId": settings.facility_code},
    )
    main.app.dependency_overrides[get_db] = override_get_db
    with TestClient(main.app) as test_client:
        test_client.headers["Authorization"] = "Bearer test-token"
        yield test_client
    main.app.dependency_overrides.clear()
    test_engine.dispose()


def test_health_is_public_but_staff_api_requires_a_facility_session(client: TestClient):
    client.headers.pop("Authorization")
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/facility").status_code == 401


def test_staff_session_cannot_access_another_facility(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {"sub": "test-staff", "facilityId": "OTHER"},
    )
    response = client.get("/api/v1/facility")
    assert response.status_code == 403


@pytest.mark.parametrize(
    "staff_role",
    [
        "admin",
        "facility_admin",
        "medical_director",
        "clinician",
        "pharmacist",
        "department_head",
    ],
)
def test_roles_requiring_mfa_cannot_access_api_before_setup(
    client: TestClient,
    monkeypatch,
    staff_role: str,
):
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-staff",
            "facilityId": settings.facility_code,
            "staffRole": staff_role,
            "mfa": False,
        },
    )
    response = client.get("/api/v1/facility")
    assert response.status_code == 403
    assert "authenticator" in response.json()["detail"]


def test_mfa_enabled_staff_role_can_access_api(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-staff",
            "facilityId": settings.facility_code,
            "staffRole": "clinician",
            "mfa": True,
        },
    )
    assert client.get("/api/v1/facility").status_code == 200


def test_other_staff_roles_do_not_require_mfa_by_default(client: TestClient, monkeypatch):
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-staff",
            "facilityId": settings.facility_code,
            "staffRole": "reception",
            "mfa": False,
        },
    )
    assert client.get("/api/v1/facility").status_code == 200


def register_patient(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "first_name": "Amina",
            "last_name": "Nabirye",
            "sex": "female",
            "date_of_birth": "1994-05-21",
            "phone": "+256700100200",
            "usual_payment_method": "cash",
            "allergies": ["Penicillin"],
        },
    )
    assert response.status_code == 201
    return response.json()


def set_staff_role(
    monkeypatch,
    staff_role: str,
    department_code: str | None = None,
    *,
    mfa: bool = True,
) -> None:
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-staff",
            "facilityId": settings.facility_code,
            "staffRole": staff_role,
            "departmentCode": department_code,
            "mfa": mfa,
        },
    )


def test_department_head_is_limited_to_assigned_module_and_requires_mfa(
    client: TestClient,
    monkeypatch,
):
    set_staff_role(monkeypatch, "department_head", "LAB", mfa=False)
    assert client.get("/api/v1/laboratory/orders").status_code == 403

    set_staff_role(monkeypatch, "department_head", "LAB")
    assert client.get("/api/v1/laboratory/orders").status_code == 200
    assert client.get("/api/v1/pharmacy/stock").status_code == 403
    assert client.get("/api/v1/patients").status_code == 403
    assert client.get(
        "/api/v1/departments/patients?department_code=LAB&q=amina"
    ).status_code == 200


def test_pharmacy_orders_only_deduct_stock_when_successfully_dispensed(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "pharmacy", "PHARM", mfa=False)
    stock = client.post(
        "/api/v1/pharmacy/stock",
        json={
            "name": "Amoxicillin",
            "strength": "500 mg",
            "form": "capsule",
            "unit": "capsule",
            "quantity_on_hand": 10,
            "reorder_level": 2,
            "unit_price": "100.00",
        },
    )
    assert stock.status_code == 201

    set_staff_role(monkeypatch, "clinician", "OPD")
    order = client.post(
        "/api/v1/pharmacy/orders",
        json={
            "patient_id": patient["id"],
            "stock_item_id": stock.json()["id"],
            "dosage": "1 capsule",
            "frequency": "3 times daily",
            "duration": "5 days",
            "quantity": 6,
        },
    )
    assert order.status_code == 201

    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    dispensed = client.post(f"/api/v1/pharmacy/orders/{order.json()['id']}/dispense")
    assert dispensed.status_code == 200
    assert dispensed.json()["status"] == "dispensed"
    assert client.get("/api/v1/pharmacy/stock").json()[0]["quantity_on_hand"] == 4
    assert client.post(f"/api/v1/pharmacy/orders/{order.json()['id']}/dispense").status_code == 409


def test_laboratory_result_can_only_be_recorded_once_by_lab_staff(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "clinician", "OPD")
    order = client.post(
        "/api/v1/laboratory/orders",
        json={
            "patient_id": patient["id"],
            "test_name": "Full blood count",
            "specimen": "Blood",
            "priority": "routine",
        },
    )
    assert order.status_code == 201

    set_staff_role(monkeypatch, "laboratory", "LAB", mfa=False)
    result = client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/result",
        json={"result": "Within expected range."},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "resulted"
    assert client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/result",
        json={"result": "Changed result."},
    ).status_code == 409


def test_billing_rejects_payments_exceeding_balance(client: TestClient, monkeypatch):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "cashier", "BILL", mfa=False)
    invoice = client.post(
        "/api/v1/billing/invoices",
        json={
            "patient_id": patient["id"],
            "description": "Consultation",
            "total_amount": "5000.00",
        },
    )
    assert invoice.status_code == 201
    invoice_id = invoice.json()["id"]
    payment = client.post(
        f"/api/v1/billing/invoices/{invoice_id}/payments",
        json={"amount": "2000.00", "method": "cash"},
    )
    assert payment.status_code == 201
    assert payment.json()["status"] == "partially_paid"
    assert payment.json()["balance"] == "3000.00"
    assert client.post(
        f"/api/v1/billing/invoices/{invoice_id}/payments",
        json={"amount": "3000.01", "method": "cash"},
    ).status_code == 409


def test_theatre_procedure_status_transitions_are_enforced(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "theatre", "THR", mfa=False)
    procedure = client.post(
        "/api/v1/theatre/procedures",
        json={
            "patient_id": patient["id"],
            "procedure_name": "Minor procedure",
            "scheduled_at": "2030-01-02T09:00:00+03:00",
            "lead_clinician": "Dr. Test",
        },
    )
    assert procedure.status_code == 201
    procedure_id = procedure.json()["id"]
    assert client.patch(
        f"/api/v1/theatre/procedures/{procedure_id}",
        json={"status": "in_progress"},
    ).status_code == 200
    assert client.patch(
        f"/api/v1/theatre/procedures/{procedure_id}",
        json={"status": "cancelled"},
    ).status_code == 409


def test_patient_profile_can_be_viewed_and_updated(client: TestClient):
    patient = register_patient(client)
    updated = client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={
            "first_name": "Amina Grace",
            "email": "amina@example.org",
            "alt_phone": "+256700100201",
            "national_id": "TEST-123",
            "next_of_kin_name": "Grace Nabirye",
            "next_of_kin_relationship": "Sister",
            "next_of_kin_phone": "+256700100202",
            "address": "Kampala",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["first_name"] == "Amina Grace"
    assert updated.json()["national_id"] == "TEST-123"
    assert updated.json()["next_of_kin_phone"] == "+256700100202"

    profile = client.get(f"/api/v1/patients/{patient['id']}")
    assert profile.status_code == 200
    assert profile.json()["patient"]["address"] == "Kampala"
    assert profile.json()["patient"]["status"] == "active"
    assert profile.json()["patient"]["sms_consent"] is False


def test_patient_archive_preserves_record_and_can_be_restored(client: TestClient):
    patient = register_patient(client)
    archived = client.delete(f"/api/v1/patients/{patient['id']}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "inactive"
    assert client.get("/api/v1/patients").json() == []

    archived_patients = client.get("/api/v1/patients?include_archived=true")
    assert archived_patients.status_code == 200
    assert archived_patients.json()[0]["id"] == patient["id"]
    assert archived_patients.json()[0]["status"] == "inactive"
    assert client.get(f"/api/v1/patients/{patient['id']}").json()["patient"]["patient_number"] == patient["patient_number"]

    restored = client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={"status": "active"},
    )
    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    assert len(client.get("/api/v1/patients").json()) == 1


def test_patient_with_open_visit_cannot_be_archived(client: TestClient):
    patient = register_patient(client)
    departments = client.get("/api/v1/facility").json()["departments"]
    department = next(item for item in departments if item["code"] == "OPD")
    visit = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": department["id"],
            "reason": "Follow-up",
            "expected_payment_method": "cash",
        },
    )
    assert visit.status_code == 201

    archived = client.delete(f"/api/v1/patients/{patient['id']}")
    assert archived.status_code == 409
    assert client.get("/api/v1/patients").json()[0]["status"] == "active"


def test_patient_checkin_triage_and_queue_call(client: TestClient):
    facility = client.get("/api/v1/facility").json()
    patient = register_patient(client)
    department = next(item for item in facility["departments"] if item["code"] == "OPD")

    checked_in = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": department["id"],
            "reason": "Headache",
            "expected_payment_method": "cash",
        },
    )
    assert checked_in.status_code == 201
    assert checked_in.json()["queue_number"] == "OPD-001"

    duplicate_visit = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": department["id"],
            "reason": "Second check-in",
        },
    )
    assert duplicate_visit.status_code == 409

    triage = client.post(
        f"/api/v1/triage/{checked_in.json()['visit_id']}",
        json={
            "temperature": 37.2,
            "pulse": 78,
            "weight": 64,
            "height": 160,
            "priority": "urgent",
            "recorded_by": "Nurse Test",
        },
    )
    assert triage.status_code == 200
    assert triage.json()["bmi"] == 25.0

    queue = client.get(f"/api/v1/queues?department_id={department['id']}").json()
    assert len(queue) == 1
    assert queue[0]["priority"] == "urgent"
    assert queue[0]["triage"]["bmi"] == 25.0

    called = client.post(
        f"/api/v1/queues/{checked_in.json()['id']}/call",
        params={"staff_name": "Dr Test"},
    )
    assert called.status_code == 200
    assert called.json()["status"] == "in_service"

    audit = client.get("/api/v1/audit").json()
    assert [event["action"] for event in audit][:3] == [
        "queue.patient_called",
        "triage.recorded",
        "visit.checked_in",
    ]


def test_patient_search_duplicate_prevention_and_dob_requirement(client: TestClient):
    patient = register_patient(client)

    search = client.get("/api/v1/patients", params={"q": "Amina"})
    assert search.status_code == 200
    assert search.json()[0]["id"] == patient["id"]

    duplicate = client.post(
        "/api/v1/patients",
        json={
            "first_name": "Different",
            "last_name": "Name",
            "sex": "female",
            "estimated_age": 30,
            "phone": "+256700100200",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "possible_duplicate"

    missing_age_and_dob = client.post(
        "/api/v1/patients",
        json={"first_name": "Test", "last_name": "User", "sex": "other"},
    )
    assert missing_age_and_dob.status_code == 422


def test_appointments_reject_overlapping_bookings_and_require_cancel_reason(client: TestClient):
    facility = client.get("/api/v1/facility").json()
    patient = register_patient(client)
    department = next(item for item in facility["departments"] if item["code"] == "OPD")
    start = "2027-01-05T10:00:00Z"
    end = "2027-01-05T10:30:00Z"
    payload = {
        "patient_id": patient["id"],
        "department_id": department["id"],
        "starts_at": start,
        "ends_at": end,
        "clinician": "Dr. Sample",
        "reason": "Review",
    }

    created = client.post("/api/v1/appointments", json=payload)
    assert created.status_code == 201

    conflict = client.post("/api/v1/appointments", json={**payload, "patient_id": patient["id"]})
    assert conflict.status_code == 409

    cancel_without_reason = client.patch(
        f"/api/v1/appointments/{created.json()['id']}",
        json={"status": "cancelled"},
    )
    assert cancel_without_reason.status_code == 422

    cancel = client.patch(
        f"/api/v1/appointments/{created.json()['id']}",
        json={"status": "cancelled", "cancellation_reason": "Patient requested"},
    )
    assert cancel.status_code == 200


def test_reminder_fires_once_and_notification_can_be_marked_read(client: TestClient):
    reminder_response = client.post(
        "/api/v1/reminders",
        json={
            "title": "Check appointment schedule",
            "due_at": "2026-01-01T10:00:00Z",
            "timezone": "Africa/Kampala",
            "priority": "high",
        },
    )
    assert reminder_response.status_code == 201
    reminder_id = reminder_response.json()["id"]

    with main.SessionLocal() as db:
        assert process_due_occurrences(db) == 1
    with main.SessionLocal() as db:
        assert process_due_occurrences(db) == 0

    listed = client.get("/api/v1/notifications")
    assert listed.status_code == 200
    assert listed.json()["unread_count"] == 1
    notification = listed.json()["items"][0]
    assert notification["title"] == "Check appointment schedule"
    assert notification["priority"] == "high"

    marked = client.post(
        "/api/v1/notifications/read",
        json={"notification_ids": [notification["id"]]},
    )
    assert marked.status_code == 200
    assert marked.json()["updated"] == 1
    assert client.get("/api/v1/notifications").json()["unread_count"] == 0

    with main.SessionLocal() as db:
        assert db.query(Reminder).filter_by(id=reminder_id).one().status == "scheduled"
        assert db.query(ReminderOccurrence).filter_by(reminder_id=reminder_id).one().status == "fired"
        assert db.query(Notification).filter_by(id=notification["id"]).count() == 1


def test_reminders_are_private_and_reject_invalid_schedule(client: TestClient, monkeypatch):
    created = client.post(
        "/api/v1/reminders",
        json={
            "title": "Private reminder",
            "due_at": "2027-01-01T10:00:00Z",
            "timezone": "Africa/Kampala",
        },
    )
    assert created.status_code == 201
    reminder_id = created.json()["id"]

    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "another-staff-member",
            "facilityId": settings.facility_code,
        },
    )
    assert client.get("/api/v1/reminders").json() == []
    assert client.patch(
        f"/api/v1/reminders/{reminder_id}",
        json={"action": "done"},
    ).status_code == 404

    invalid = client.post(
        "/api/v1/reminders",
        json={
            "title": "Invalid reminder",
            "due_at": "2027-01-01T10:00:00",
            "timezone": "Not/A_Timezone",
            "alert_offsets": [10],
        },
    )
    assert invalid.status_code == 422


def test_snoozing_reminder_only_schedules_the_snooze_and_repeating_reminders_advance(client: TestClient):
    snooze_target = datetime.now(timezone.utc) + timedelta(minutes=10)
    created = client.post(
        "/api/v1/reminders",
        json={
            "title": "Snoozable reminder",
            "due_at": "2027-01-01T10:00:00Z",
            "timezone": "Africa/Kampala",
            "alert_offsets": [0, 60, 1440],
        },
    )
    assert created.status_code == 201
    snoozed = client.patch(
        f"/api/v1/reminders/{created.json()['id']}",
        json={"action": "snooze", "snooze_until": snooze_target.isoformat()},
    )
    assert snoozed.status_code == 200
    with main.SessionLocal() as db:
        occurrences = (
            db.query(ReminderOccurrence)
            .filter_by(reminder_id=created.json()["id"])
            .all()
        )
        pending = [item for item in occurrences if item.status == "pending"]
        assert len(pending) == 1
        assert pending[0].alert_offset_minutes == 0

    repeating = client.post(
        "/api/v1/reminders",
        json={
            "title": "Daily reminder",
            "due_at": "2026-01-01T10:00:00Z",
            "timezone": "Africa/Kampala",
            "repeat_frequency": "daily",
        },
    )
    assert repeating.status_code == 201
    with main.SessionLocal() as db:
        assert process_due_occurrences(db) == 1
    with main.SessionLocal() as db:
        daily = db.query(Reminder).filter_by(id=repeating.json()["id"]).one()
        assert daily.status == "scheduled"
        assert daily.due_at.date().isoformat() == "2026-01-02"
        assert (
            db.query(ReminderOccurrence)
            .filter_by(reminder_id=daily.id, status="pending")
            .count()
            == 1
        )
