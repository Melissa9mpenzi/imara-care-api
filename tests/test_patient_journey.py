from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base, build_engine, get_db
from app import main
from app import security
from app.config import settings
from app.models import JobRun, MedicationStockBatch, Notification, Reminder, ReminderOccurrence
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

    monkeypatch.setattr(main, "SessionLocal", test_session_factory)
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-staff",
            "name": "Test Facility Admin",
            "email": "admin@example.org",
            "facilityId": settings.facility_code,
            "staffRole": "facility_admin",
            "mfa": True,
        },
    )
    main.app.dependency_overrides[get_db] = override_get_db
    Base.metadata.create_all(bind=test_engine)
    main.initialize_database()
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
        "nurse",
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


def test_reception_can_register_but_only_records_can_edit_or_archive(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "reception", mfa=False)
    assert client.get("/api/v1/patients").status_code == 200
    assert client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={"phone": "+256700100201"},
    ).status_code == 403
    assert client.delete(f"/api/v1/patients/{patient['id']}").status_code == 403
    assert client.post(
        "/api/v1/patients",
        json={
            "first_name": "Reception",
            "last_name": "Registration",
            "sex": "female",
            "date_of_birth": "1994-05-21",
            "usual_payment_method": "cash",
        },
    ).status_code == 201

    set_staff_role(monkeypatch, "records", mfa=False)
    assert client.patch(
        f"/api/v1/patients/{patient['id']}",
        json={"phone": "+256700100202"},
    ).status_code == 200


def test_patient_spreadsheet_import_previews_creates_and_skips_duplicates_and_invalid_rows(
    client: TestClient,
    monkeypatch,
):
    set_staff_role(monkeypatch, "reception", mfa=False)
    content = (
        "first_name,last_name,sex,date_of_birth,estimated_age,phone\n"
        "Grace,Nakato,female,1992-03-14,,+256700123456\n"
        "Another,Name,female,1990-01-01,,+256700123456\n"
        "No,Age,male,,,\n"
    ).encode()
    upload = {"file": ("patients.csv", content, "text/csv")}

    preview = client.post("/api/v1/patients/import?preview=true", files=upload)
    assert preview.status_code == 200
    assert preview.json()["ready"] == 1
    assert preview.json()["duplicates"] == 1
    assert preview.json()["invalid"] == 1
    assert client.get("/api/v1/patients").json() == []

    imported = client.post("/api/v1/patients/import", files=upload)
    assert imported.status_code == 200
    assert imported.json()["created"] == 1
    assert imported.json()["duplicates"] == 1
    assert imported.json()["invalid"] == 1
    patients = client.get("/api/v1/patients").json()
    assert len(patients) == 1
    assert patients[0]["first_name"] == "Grace"
    assert client.post("/api/v1/patients/import", files=upload).json()["created"] == 0


def test_patient_spreadsheet_import_is_not_available_to_clinicians(
    client: TestClient,
    monkeypatch,
):
    set_staff_role(monkeypatch, "clinician")
    response = client.post(
        "/api/v1/patients/import?preview=true",
        files={"file": ("patients.csv", b"first_name,last_name,sex\n", "text/csv")},
    )
    assert response.status_code == 403


def test_patient_spreadsheet_import_accepts_xlsx_and_rejects_formula_cells(
    client: TestClient,
    monkeypatch,
):
    set_staff_role(monkeypatch, "records", mfa=False)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["first_name", "last_name", "sex", "date_of_birth"])
    sheet.append(["Nora", "Kato", "female", "1993-04-02"])
    contents = BytesIO()
    workbook.save(contents)

    response = client.post(
        "/api/v1/patients/import?preview=true",
        files={
            "file": (
                "patients.xlsx",
                contents.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["ready"] == 1

    formula_book = Workbook()
    formula_sheet = formula_book.active
    formula_sheet.append(["first_name", "last_name", "sex", "date_of_birth"])
    formula_sheet.append(["=1+1", "Formula", "female", "1993-04-02"])
    formula_contents = BytesIO()
    formula_book.save(formula_contents)
    formula_response = client.post(
        "/api/v1/patients/import?preview=true",
        files={
            "file": (
                "patients.xlsx",
                formula_contents.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert formula_response.status_code == 422
    assert "formula" in formula_response.json()["detail"].lower()


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
    assert client.get(
        "/api/v1/departments/patients?department_code=PHARM&q=amina"
    ).status_code == 403


def test_department_head_only_sees_patients_and_queue_in_assigned_department(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    facility = client.get("/api/v1/facility").json()
    lab = next(item for item in facility["departments"] if item["code"] == "LAB")
    opd = next(item for item in facility["departments"] if item["code"] == "OPD")
    checked_in = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": lab["id"],
            "reason": "Synthetic lab test",
        },
    )
    assert checked_in.status_code == 201
    other_patient_response = client.post(
        "/api/v1/patients",
        json={
            "first_name": "Daniel",
            "last_name": "Okello",
            "sex": "male",
            "date_of_birth": "1986-03-14",
            "phone": "+256700100203",
            "usual_payment_method": "cash",
        },
    )
    assert other_patient_response.status_code == 201
    other_patient = other_patient_response.json()
    client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": other_patient["id"],
            "department_id": opd["id"],
            "reason": "General consultation",
        },
    )

    set_staff_role(monkeypatch, "department_head", "LAB")
    department_patients = client.get(
        "/api/v1/departments/patients?department_code=LAB&limit=50"
    )
    assert department_patients.status_code == 200
    assert [item["id"] for item in department_patients.json()] == [patient["id"]]

    department_queue = client.get(
        "/api/v1/departments/queues?department_code=LAB&status=all"
    )
    assert department_queue.status_code == 200
    assert len(department_queue.json()) == 1
    assert department_queue.json()[0]["patient"]["id"] == patient["id"]
    assert client.get(
        "/api/v1/departments/queues?department_code=OPD&status=all"
    ).status_code == 403
    assert client.get("/api/v1/queues?status=all").status_code == 403


def test_pharmacist_can_search_active_facility_patients_without_pharmacy_visit(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "pharmacist", "PHARM")

    response = client.get(
        "/api/v1/departments/patients?department_code=PHARM&q=amina"
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [patient["id"]]


def test_specialist_roles_cannot_access_general_patients_or_other_departments(
    client: TestClient,
    monkeypatch,
):
    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    assert client.get("/api/v1/pharmacy/stock").status_code == 200
    assert client.get("/api/v1/patients").status_code == 403
    assert client.get("/api/v1/billing/invoices").status_code == 403
    assert client.get(
        "/api/v1/departments/patients?department_code=LAB"
    ).status_code == 403


def test_nurse_access_is_scoped_to_assigned_department_queue(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    facility = client.get("/api/v1/facility").json()
    departments = {item["code"]: item for item in facility["departments"]}
    lab_visit = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": departments["LAB"]["id"],
            "reason": "Synthetic lab queue test",
        },
    )
    opd_visit = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": departments["OPD"]["id"],
            "reason": "Synthetic outpatient queue test",
        },
    )
    assert lab_visit.status_code == opd_visit.status_code == 201

    set_staff_role(monkeypatch, "nurse", "LAB")
    scoped_facility = client.get("/api/v1/facility")
    assert [item["code"] for item in scoped_facility.json()["departments"]] == ["LAB"]
    assert client.get("/api/v1/dashboard").status_code == 403
    assert client.get("/api/v1/patients").status_code == 403
    assert client.get("/api/v1/appointments").status_code == 403
    assert client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": departments["LAB"]["id"],
            "reason": "Nurse cannot check in",
        },
    ).status_code == 403

    own_queue = client.get(
        f"/api/v1/queues?status=all&department_id={departments['LAB']['id']}"
    )
    assert own_queue.status_code == 200
    assert len(own_queue.json()) == 1
    assert own_queue.json()[0]["id"] == lab_visit.json()["id"]
    assert client.get(
        f"/api/v1/queues?status=all&department_id={departments['OPD']['id']}"
    ).status_code == 403
    assert client.post(
        f"/api/v1/triage/{opd_visit.json()['visit_id']}",
        json={"recorded_by": "Test Nurse"},
    ).status_code == 403
    assert client.post(
        f"/api/v1/triage/{lab_visit.json()['visit_id']}",
        json={"recorded_by": "Test Nurse"},
    ).status_code == 200
    assert client.post(
        f"/api/v1/queues/{lab_visit.json()['id']}/call"
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
            "batch_number": "AMX-001",
            "expires_on": "2028-12-31",
            "reference": "DELIVERY-AMX-001",
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


def test_pharmacy_stock_spreadsheet_import_requires_restock_confirmation_and_reference(
    client: TestClient,
    monkeypatch,
):
    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    existing = client.post(
        "/api/v1/pharmacy/stock",
        json={
            "name": "Ibuprofen",
            "strength": "200 mg",
            "form": "tablet",
            "unit": "tablet",
            "quantity_on_hand": 8,
            "batch_number": "IBU-OPEN-01",
            "expires_on": "2028-12-31",
            "reference": "DELIVERY-IBU-001",
        },
    )
    assert existing.status_code == 201
    content = (
        "name,strength,form,unit,quantity_on_hand,reorder_level,unit_price,batch_number,expires_on\n"
        "Ibuprofen,200 mg,tablet,tablet,5,3,100,IBU-NEW-02,2028-12-31\n"
        "Paracetamol,500 mg,tablet,tablet,12,4,50,PAR-NEW-01,2028-12-31\n"
        "Paracetamol,500 mg,tablet,tablet,2,4,50,PAR-NEW-02,2029-12-31\n"
        "Paracetamol,500 mg,tablet,tablet,12,4,50,PAR-NEW-01,2028-12-31\n"
        "Aspirin,75 mg,tablet,tablet,0,2,25,,\n"
    ).encode()
    upload = {"file": ("stock.csv", content, "text/csv")}
    reference = "DELIVERY-2026-001"

    preview = client.post(
        "/api/v1/pharmacy/stock/import?preview=true",
        data={"reference": reference},
        files=upload,
    )
    assert preview.status_code == 200
    assert preview.json()["restock"] == 1
    assert preview.json()["new"] == 1
    assert preview.json()["duplicates"] == 1
    assert preview.json()["invalid"] == 1
    assert client.get("/api/v1/pharmacy/stock").json()[0]["quantity_on_hand"] == 8

    unconfirmed = client.post(
        "/api/v1/pharmacy/stock/import",
        data={"reference": reference},
        files=upload,
    )
    assert unconfirmed.status_code == 400

    imported = client.post(
        "/api/v1/pharmacy/stock/import",
        data={"reference": reference, "confirm_restock_matches": "true"},
        files=upload,
    )
    assert imported.status_code == 200
    assert imported.json()["created"] == 1
    assert imported.json()["restocked"] == 1
    imported_stock = client.get(
        "/api/v1/pharmacy/stock"
    ).json()
    assert sorted(item["quantity_on_hand"] for item in imported_stock) == [13, 14]
    paracetamol = next(item for item in imported_stock if item["name"] == "Paracetamol")
    assert len(paracetamol["batches"]) == 2
    reused_reference = client.post(
        "/api/v1/pharmacy/stock/import?preview=true",
        data={"reference": reference},
        files=upload,
    )
    assert reused_reference.status_code == 409


def test_pharmacy_dispensing_uses_earliest_expiry_batch_first(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    item = client.post(
        "/api/v1/pharmacy/stock",
        json={
            "name": "Demo medicine",
            "strength": "10 mg",
            "form": "tablet",
            "unit": "tablet",
            "quantity_on_hand": 5,
            "batch_number": "EARLY-LOT",
            "expires_on": (date.today() + timedelta(days=30)).isoformat(),
            "reference": "DELIVERY-EARLY",
        },
    )
    assert item.status_code == 201
    received = client.post(
        f"/api/v1/pharmacy/stock/{item.json()['id']}/receive",
        json={
            "quantity": 10,
            "batch_number": "LATE-LOT",
            "expires_on": (date.today() + timedelta(days=90)).isoformat(),
            "reference": "DELIVERY-LATE",
        },
    )
    assert received.status_code == 200

    set_staff_role(monkeypatch, "clinician", "OPD")
    order = client.post(
        "/api/v1/pharmacy/orders",
        json={
            "patient_id": patient["id"],
            "stock_item_id": item.json()["id"],
            "dosage": "1 tablet",
            "frequency": "once daily",
            "quantity": 7,
        },
    )
    assert order.status_code == 201

    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    dispensed = client.post(f"/api/v1/pharmacy/orders/{order.json()['id']}/dispense")
    assert dispensed.status_code == 200
    stock = client.get("/api/v1/pharmacy/stock").json()[0]
    assert stock["quantity_on_hand"] == 8
    assert stock["available_quantity"] == 8
    assert stock["batches"] == [{
        "batch_number": "LATE-LOT",
        "expires_on": (date.today() + timedelta(days=90)).isoformat(),
        "quantity_remaining": 8,
        "expired": False,
    }]


def test_expired_stock_is_excluded_from_available_quantity_and_dispensing(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    item = client.post(
        "/api/v1/pharmacy/stock",
        json={
            "name": "Expired medicine",
            "strength": "5 mg",
            "form": "tablet",
            "unit": "tablet",
            "quantity_on_hand": 5,
            "batch_number": "EXP-LOT",
            "expires_on": (date.today() + timedelta(days=30)).isoformat(),
            "reference": "DELIVERY-EXP",
        },
    )
    assert item.status_code == 201
    with main.SessionLocal() as db:
        batch = db.scalar(
            select(MedicationStockBatch).where(
                MedicationStockBatch.stock_item_id == item.json()["id"]
            )
        )
        assert batch is not None
        batch.expires_on = date.today() - timedelta(days=1)
        db.commit()

    stock = client.get("/api/v1/pharmacy/stock").json()[0]
    assert stock["quantity_on_hand"] == 5
    assert stock["available_quantity"] == 0
    assert stock["expired_quantity"] == 5

    set_staff_role(monkeypatch, "clinician", "OPD")
    order = client.post(
        "/api/v1/pharmacy/orders",
        json={
            "patient_id": patient["id"],
            "stock_item_id": item.json()["id"],
            "dosage": "1 tablet",
            "frequency": "once daily",
            "quantity": 1,
        },
    )
    assert order.status_code == 201
    set_staff_role(monkeypatch, "pharmacist", "PHARM")
    refused = client.post(f"/api/v1/pharmacy/orders/{order.json()['id']}/dispense")
    assert refused.status_code == 409
    assert "unexpired" in refused.json()["detail"]


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
    not_collected = client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/result",
        json={"result": "Within expected range."},
    )
    assert not_collected.status_code == 409

    collected = client.patch(
        f"/api/v1/laboratory/orders/{order.json()['id']}/sample",
        json={"status": "collected"},
    )
    assert collected.status_code == 200
    assert collected.json()["sample_status"] == "collected"

    result = client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/result",
        json={"result": "Within expected range."},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "resulted"
    assert result.json()["sample_status"] == "resulted"
    assert result.json()["review_status"] == "awaiting_review"
    assert client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/result",
        json={"result": "Changed result."},
    ).status_code == 409
    assert client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/review",
        json={"notes": "Reviewed by the attending clinician."},
    ).status_code == 403

    set_staff_role(monkeypatch, "clinician", "OPD")
    reviewed = client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/review",
        json={"notes": "Reviewed by the attending clinician."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "reviewed"
    assert reviewed.json()["reviewed_by"] == "test-staff"
    assert client.post(
        f"/api/v1/laboratory/orders/{order.json()['id']}/review",
        json={},
    ).status_code == 409


def test_billing_rejects_payments_exceeding_balance(client: TestClient, monkeypatch):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "billing", "BILL", mfa=False)
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
    set_staff_role(monkeypatch, "cashier", "BILL", mfa=False)
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


def test_billing_itemizes_charges_and_prefills_registered_patient_contact(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "billing", "BILL", mfa=False)

    patient_search = client.get(
        "/api/v1/departments/patients?department_code=BILL&q=Amina"
    )
    assert patient_search.status_code == 200
    assert patient_search.json()[0]["id"] == patient["id"]
    assert patient_search.json()[0]["phone"] == "+256700100200"

    invoice = client.post(
        "/api/v1/billing/invoices",
        json={
            "patient_id": patient["id"],
            "description": "Consultation + 1 more",
            "items": [
                {
                    "description": "Consultation",
                    "unit": "visit",
                    "quantity": "1.15",
                    "unit_price": "0.10",
                },
                {
                    "description": "Laboratory test",
                    "unit": "test",
                    "quantity": "2.00",
                    "unit_price": "100.00",
                },
            ],
            "bill_to_name": "Amina Nabirye",
            "bill_to_phone": "+256700100200",
            "payer_type": "insurance",
            "insurer_name": "Imara Health",
            "payer_reference": "MEM-001",
            "service_date": "2025-03-10",
            "due_date": "2025-03-20",
            "notes": "Front desk payment plan.",
        },
    )
    assert invoice.status_code == 201
    created = invoice.json()
    assert created["total_amount"] == "200.12"
    assert [item["amount"] for item in created["items"]] == ["0.12", "200.00"]
    assert created["billing_details"] == {
        "bill_to_name": "Amina Nabirye",
        "bill_to_phone": "+256700100200",
        "payer_type": "insurance",
        "insurer_name": "Imara Health",
        "payer_reference": "MEM-001",
        "service_date": "2025-03-10",
        "due_date": "2025-03-20",
        "notes": "Front desk payment plan.",
    }

    listed = client.get("/api/v1/billing/invoices")
    assert listed.status_code == 200
    assert listed.json()[0]["patient"]["phone"] == "+256700100200"
    assert listed.json()[0]["items"] == created["items"]
    assert listed.json()[0]["insurance_claim"] is None

    claim = client.post(
        f"/api/v1/billing/invoices/{created['id']}/claims",
        json={"notes": "Prepared for insurer submission."},
    )
    assert claim.status_code == 201
    assert claim.json()["status"] == "draft"
    assert claim.json()["insurer_name"] == "Imara Health"
    assert client.post(
        f"/api/v1/billing/invoices/{created['id']}/claims",
        json={},
    ).status_code == 409

    claim_id = claim.json()["id"]
    set_staff_role(monkeypatch, "cashier", "BILL", mfa=False)
    assert client.patch(
        f"/api/v1/billing/claims/{claim_id}",
        json={"status": "submitted"},
    ).status_code == 403
    set_staff_role(monkeypatch, "billing", "BILL", mfa=False)
    submitted = client.patch(
        f"/api/v1/billing/claims/{claim_id}",
        json={
            "status": "submitted",
            "external_claim_reference": "INS-CLAIM-001",
        },
    )
    assert submitted.status_code == 200
    assert submitted.json()["external_claim_reference"] == "INS-CLAIM-001"
    approved = client.patch(
        f"/api/v1/billing/claims/{claim_id}",
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    assert client.patch(
        f"/api/v1/billing/claims/{claim_id}",
        json={"status": "paid"},
    ).status_code == 409

    payment = client.post(
        f"/api/v1/billing/invoices/{created['id']}/payments",
        json={"amount": "200.12", "method": "insurance", "reference": "SETTLE-001"},
    )
    assert payment.status_code == 201
    assert payment.json()["payments"][0]["receipt_number"].startswith("RCT-")
    paid_claim = client.patch(
        f"/api/v1/billing/claims/{claim_id}",
        json={"status": "paid"},
    )
    assert paid_claim.status_code == 200
    assert paid_claim.json()["status"] == "paid"
    assert client.get("/api/v1/billing/invoices").json()[0]["insurance_claim"]["status"] == "paid"


def test_billing_itemized_invoice_rejects_a_mismatched_total(
    client: TestClient,
    monkeypatch,
):
    patient = register_patient(client)
    set_staff_role(monkeypatch, "billing", "BILL", mfa=False)
    response = client.post(
        "/api/v1/billing/invoices",
        json={
            "patient_id": patient["id"],
            "total_amount": "99.00",
            "items": [
                {
                    "description": "Consultation",
                    "quantity": "1",
                    "unit_price": "100.00",
                }
            ],
        },
    )
    assert response.status_code == 422


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


@pytest.mark.parametrize(
    ("target_code", "expected_visit_status", "expected_queue_number"),
    [
        ("LAB", "awaiting_lab", "LAB-001"),
        ("PHARM", "awaiting_pharmacy", "PH-001"),
    ],
)
def test_reception_can_handoff_an_open_visit_to_lab_or_pharmacy(
    client: TestClient,
    monkeypatch,
    target_code: str,
    expected_visit_status: str,
    expected_queue_number: str,
):
    departments = {
        department["code"]: department
        for department in client.get("/api/v1/facility").json()["departments"]
    }
    patient = register_patient(client)
    checked_in = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": departments["OPD"]["id"],
            "reason": "Persistent headache",
            "expected_payment_method": "cash",
        },
    )
    assert checked_in.status_code == 201

    set_staff_role(monkeypatch, "reception", mfa=False)
    response = client.post(
        f"/api/v1/visits/{checked_in.json()['visit_id']}/handoff",
        json={"target_department_code": target_code, "reason": "Request follow-up"},
    )
    assert response.status_code == 201
    result = response.json()
    assert result["target_visit"]["department"]["code"] == target_code
    assert result["target_visit"]["reason"] == "Request follow-up"
    assert result["target_visit"]["queue_number"] == expected_queue_number

    outpatient_queue = client.get(
        "/api/v1/queues",
        params={"department_id": departments["OPD"]["id"], "status": "all"},
    ).json()
    assert outpatient_queue[0]["status"] == "completed"
    assert outpatient_queue[0]["visit_status"] == expected_visit_status
    set_staff_role(monkeypatch, "facility_admin")
    audit = client.get("/api/v1/audit").json()
    assert any(event["action"] == "visit.handed_off" for event in audit)

    duplicate = client.post(
        f"/api/v1/visits/{checked_in.json()['visit_id']}/handoff",
        json={"target_department_code": target_code, "reason": "Repeat referral"},
    )
    assert duplicate.status_code == 409


def test_nurse_cannot_handoff_a_visit_outside_assigned_department(
    client: TestClient,
    monkeypatch,
):
    departments = {
        department["code"]: department
        for department in client.get("/api/v1/facility").json()["departments"]
    }
    patient = register_patient(client)
    checked_in = client.post(
        "/api/v1/visits/checkin",
        json={
            "patient_id": patient["id"],
            "department_id": departments["OPD"]["id"],
            "reason": "Persistent headache",
            "expected_payment_method": "cash",
        },
    )
    assert checked_in.status_code == 201

    set_staff_role(monkeypatch, "nurse", "LAB")
    response = client.post(
        f"/api/v1/visits/{checked_in.json()['visit_id']}/handoff",
        json={"target_department_code": "PHARM", "reason": "Dispense medication"},
    )
    assert response.status_code == 403


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


def test_reminder_scheduler_endpoint_records_a_run_and_exposes_admin_status(
    client: TestClient,
    monkeypatch,
):
    cron_secret = "test-cron-secret-with-at-least-32-chars"
    monkeypatch.setattr(settings, "cron_secret", cron_secret)
    unauthorized = client.post(
        "/api/v1/internal/jobs/reminders",
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert unauthorized.status_code == 401

    triggered = client.post(
        "/api/v1/internal/jobs/reminders",
        headers={"Authorization": f"Bearer {cron_secret}"},
    )
    assert triggered.status_code == 200
    assert triggered.json()["status"] == "succeeded"
    assert triggered.json()["processed"] == 0
    assert triggered.json()["finished_at"].endswith("+00:00")

    status_response = client.get("/api/v1/operations/reminders")
    assert status_response.status_code == 200
    assert status_response.json()["last_run"]["status"] == "succeeded"
    assert status_response.json()["stale"] is False
    assert status_response.json()["last_run"]["finished_at"].endswith("+00:00")
    with main.SessionLocal() as db:
        assert db.query(JobRun).filter_by(name="reminders").count() == 1


def test_reminder_scheduler_endpoint_fails_closed_when_secret_is_unset(
    client: TestClient,
    monkeypatch,
):
    for secret in ("", "too-short"):
        monkeypatch.setattr(settings, "cron_secret", secret)
        response = client.post("/api/v1/internal/jobs/reminders")
        assert response.status_code == 503


def test_reminder_health_is_privileged_and_stale_without_recent_run(
    client: TestClient,
    monkeypatch,
):
    from app import security

    unauthorized_staff = {
        "sub": "clinician",
        "facilityId": settings.facility_code,
        "staffRole": "clinician",
        "mfa": True,
    }
    monkeypatch.setattr(security, "verify_access_token", lambda token: unauthorized_staff)
    assert client.get("/api/v1/operations/reminders").status_code == 403

    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-admin",
            "facilityId": settings.facility_code,
            "staffRole": "facility_admin",
            "mfa": True,
        },
    )
    response = client.get("/api/v1/operations/reminders")
    assert response.status_code == 200
    assert response.json()["last_run"] is None
    assert response.json()["stale"] is True


def test_reminder_health_marks_a_slow_heartbeat_stale(client: TestClient):
    with main.SessionLocal() as db:
        finished_at = datetime.now(timezone.utc) - timedelta(minutes=6)
        db.add(
            JobRun(
                name="reminders",
                status="succeeded",
                started_at=finished_at - timedelta(seconds=2),
                finished_at=finished_at,
                processed_count=1,
            )
        )
        db.commit()

    response = client.get("/api/v1/operations/reminders")
    assert response.status_code == 200
    assert response.json()["stale"] is True


def test_failed_reminder_job_is_recorded_before_error_is_raised(monkeypatch):
    from app import reminder_worker

    test_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=test_engine)
    test_session_factory = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)

    def fail_processing(db):
        raise RuntimeError("sensitive exception details are not persisted")

    monkeypatch.setattr(reminder_worker, "process_due_occurrences", fail_processing)
    try:
        with test_session_factory() as db:
            with pytest.raises(RuntimeError):
                reminder_worker.run_reminder_job(db)
            failed_run = db.query(JobRun).filter_by(name="reminders").one()
            assert failed_run.status == "failed"
            assert failed_run.error == "RuntimeError"
            assert "sensitive" not in (failed_run.error or "")
    finally:
        test_engine.dispose()


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


def test_support_requests_are_private_and_managers_can_track_them(
    client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "test-staff",
            "name": "Amina Staff",
            "email": "amina.staff@example.org",
            "facilityId": settings.facility_code,
        },
    )
    created = client.post(
        "/api/v1/support/requests",
        json={
            "category": "technical",
            "subject": "Dashboard loading issue",
            "message": "The dashboard did not load after signing in.",
        },
    )
    assert created.status_code == 201
    ticket = created.json()
    assert ticket["ticket_number"].startswith("SUP-")
    assert ticket["status"] == "open"

    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "another-staff",
            "name": "Another Staff",
            "email": "another.staff@example.org",
            "facilityId": settings.facility_code,
            "staffRole": "reception",
        },
    )
    assert client.get("/api/v1/support/requests").json() == []
    assert client.patch(
        f"/api/v1/support/requests/{ticket['id']}",
        json={"status": "resolved"},
    ).status_code == 403

    monkeypatch.setattr(
        security,
        "verify_access_token",
        lambda token: {
            "sub": "facility-manager",
            "name": "Facility Manager",
            "email": "manager@example.org",
            "facilityId": settings.facility_code,
            "staffRole": "facility_admin",
            "mfa": True,
        },
    )
    manager_list = client.get("/api/v1/support/requests")
    assert manager_list.status_code == 200
    assert manager_list.json()[0]["id"] == ticket["id"]

    updated = client.patch(
        f"/api/v1/support/requests/{ticket['id']}",
        json={"status": "in_progress"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"


def test_support_request_rejects_empty_and_oversized_content(client: TestClient):
    empty = client.post(
        "/api/v1/support/requests",
        json={
            "category": "technical",
            "subject": "  ",
            "message": "          ",
        },
    )
    assert empty.status_code == 422

    oversized = client.post(
        "/api/v1/support/requests",
        json={
            "category": "technical",
            "subject": "Long message",
            "message": "x" * 2001,
        },
    )
    assert oversized.status_code == 422


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
