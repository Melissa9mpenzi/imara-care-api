from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app import main
from app import security
from app.config import settings


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
