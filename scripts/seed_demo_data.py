import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.main import DEFAULT_DEPARTMENTS, initialize_database
from app.models import (
    Appointment,
    BillingInvoice,
    BillingPayment,
    Department,
    Facility,
    LaboratoryOrder,
    MedicationOrder,
    MedicationStockItem,
    Patient,
    QueueEntry,
    TheatreProcedure,
    TriageRecord,
    Visit,
)

SEED_KEY = "imara-care-demo-sample-v1"


def demo_id(key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{SEED_KEY}:{key}"))


def require_local_development_database() -> None:
    if settings.environment.lower() not in {"development", "test"}:
        raise SystemExit("Demo data can only be seeded when ENVIRONMENT is development or test.")
    if not settings.database_url.startswith("sqlite"):
        raise SystemExit("Demo data seeding is restricted to a local SQLite database.")


def demo_patients(facility_id: str) -> list[Patient]:
    return [
        Patient(
            id=demo_id("patient-1"),
            facility_id=facility_id,
            patient_number="DEMO-0001",
            first_name="Amina",
            other_names="Mirembe",
            last_name="Nabirye",
            sex="female",
            date_of_birth=datetime(1992, 4, 12).date(),
            phone="+256000000001",
            alt_phone="+256000002001",
            email="amina.nabirye@example.test",
            national_id="TEST-NIN-0001",
            address="Synthetic test address 1, Kampala",
            next_of_kin_name="Mariam Nabirye",
            next_of_kin_relationship="Sister",
            next_of_kin_phone="+256000001001",
            usual_payment_method="cash",
            allergies=["Synthetic test allergy: penicillin"],
            sms_consent=False,
            status="active",
        ),
        Patient(
            id=demo_id("patient-2"),
            facility_id=facility_id,
            patient_number="DEMO-0002",
            first_name="Daniel",
            other_names="Mugisha",
            last_name="Kato",
            sex="male",
            date_of_birth=datetime(1986, 9, 3).date(),
            phone="+256000000002",
            alt_phone="+256000002002",
            email="daniel.kato@example.test",
            national_id="TEST-NIN-0002",
            address="Synthetic test address 2, Kampala",
            next_of_kin_name="Sarah Kato",
            next_of_kin_relationship="Spouse",
            next_of_kin_phone="+256000001002",
            usual_payment_method="insurance",
            allergies=[],
            sms_consent=False,
            status="active",
        ),
        Patient(
            id=demo_id("patient-3"),
            facility_id=facility_id,
            patient_number="DEMO-0003",
            first_name="Grace",
            other_names="Achen",
            last_name="Nansubuga",
            sex="female",
            date_of_birth=datetime(2001, 1, 21).date(),
            phone="+256000000003",
            alt_phone="+256000002003",
            email="grace.nansubuga@example.test",
            national_id="TEST-NIN-0003",
            address="Synthetic test address 3, Kampala",
            next_of_kin_name="Joseph Nansubuga",
            next_of_kin_relationship="Parent",
            next_of_kin_phone="+256000001003",
            usual_payment_method="mobile_money",
            allergies=[],
            sms_consent=False,
            status="active",
        ),
        Patient(
            id=demo_id("patient-4"),
            facility_id=facility_id,
            patient_number="DEMO-0004",
            first_name="Peter",
            other_names="Kizito",
            last_name="Okello",
            sex="male",
            date_of_birth=datetime(1978, 6, 15).date(),
            phone="+256000000004",
            alt_phone="+256000002004",
            email="peter.okello@example.test",
            national_id="TEST-NIN-0004",
            address="Synthetic test address 4, Kampala",
            next_of_kin_name="Grace Okello",
            next_of_kin_relationship="Sister",
            next_of_kin_phone="+256000001004",
            usual_payment_method="cash",
            allergies=[],
            sms_consent=False,
            status="active",
        ),
    ]


def refresh_existing_demo_data(db: Session, facility_id: str) -> None:
    patients = demo_patients(facility_id)
    for template in patients:
        patient = db.get(Patient, template.id)
        if patient is None:
            raise RuntimeError("The synthetic patient records are incomplete; no data was refreshed.")
        patient.first_name = template.first_name
        patient.other_names = template.other_names
        patient.last_name = template.last_name
        patient.sex = template.sex
        patient.date_of_birth = template.date_of_birth
        patient.phone = template.phone
        patient.alt_phone = template.alt_phone
        patient.email = template.email
        patient.national_id = template.national_id
        patient.address = template.address
        patient.next_of_kin_name = template.next_of_kin_name
        patient.next_of_kin_relationship = template.next_of_kin_relationship
        patient.next_of_kin_phone = template.next_of_kin_phone
        patient.usual_payment_method = template.usual_payment_method
        patient.allergies = template.allergies
        patient.sms_consent = template.sms_consent

    visits = [
        ("visit-1", "Routine consultation"),
        ("visit-2", "Blood test follow-up"),
        ("visit-3", "Prescription collection"),
        ("visit-4", "Pre-operative assessment"),
    ]
    for key, reason in visits:
        visit = db.get(Visit, demo_id(key))
        if visit is None:
            raise RuntimeError("The synthetic visit records are incomplete; no data was refreshed.")
        visit.reason = reason

    triage = db.get(TriageRecord, demo_id("triage-1"))
    appointment = db.get(Appointment, demo_id("appointment-1"))
    stock = db.get(MedicationStockItem, demo_id("stock-1"))
    medication_order = db.get(MedicationOrder, demo_id("medication-order-1"))
    lab_order = db.get(LaboratoryOrder, demo_id("lab-order-1"))
    invoice = db.get(BillingInvoice, demo_id("invoice-1"))
    payment = db.get(BillingPayment, demo_id("payment-1"))
    procedure = db.get(TheatreProcedure, demo_id("procedure-1"))
    if (
        triage is None
        or appointment is None
        or stock is None
        or medication_order is None
        or lab_order is None
        or invoice is None
        or payment is None
        or procedure is None
    ):
        raise RuntimeError("The synthetic workflow records are incomplete; no data was refreshed.")

    conflicting_stock = db.scalar(
        select(MedicationStockItem).where(
            MedicationStockItem.facility_id == facility_id,
            MedicationStockItem.name == "Paracetamol (test stock)",
            MedicationStockItem.strength == stock.strength,
            MedicationStockItem.form == stock.form,
            MedicationStockItem.id != stock.id,
        )
    )
    if conflicting_stock is not None:
        raise RuntimeError(
            "The synthetic medicine name conflicts with another stock item; no data was refreshed."
        )

    triage.notes = "Synthetic test data only."
    triage.recorded_by = "Synthetic test nurse"
    appointment.clinician = "Dr. Susan Nakato"
    appointment.reason = "Follow-up consultation"
    appointment.notes = "Synthetic test appointment."
    stock.name = "Paracetamol (test stock)"
    medication_order.instructions = "Synthetic test only; not a real prescription."
    medication_order.prescribed_by = "synthetic-test-clinician"
    lab_order.test_name = "Full blood count (test order)"
    lab_order.specimen = "Simulated blood specimen"
    lab_order.clinical_notes = "Synthetic workflow test only; no real results."
    lab_order.ordered_by = "synthetic-test-clinician"
    invoice.description = "Consultation charge (test)"
    invoice.created_by = "synthetic-test-billing"
    payment.recorded_by = "synthetic-test-cashier"
    procedure.procedure_name = "Minor outpatient procedure (test)"
    procedure.lead_clinician = "Dr. Susan Nakato"
    procedure.notes = "Synthetic workflow test only; no real procedure."
    procedure.created_by = "synthetic-test-theatre"


def seed_demo_data(refresh_existing: bool = False) -> bool:
    initialize_database()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with SessionLocal() as db:
        facility = db.scalar(
            select(Facility).where(Facility.code == settings.facility_code)
        )
        if facility is None:
            raise RuntimeError("The configured demo facility was not initialized.")
        if db.get(Patient, demo_id("patient-1")) is not None:
            if refresh_existing:
                refresh_existing_demo_data(db, facility.id)
                db.commit()
            return False

        departments = {
            department.code: department
            for department in db.scalars(
                select(Department).where(Department.facility_id == facility.id)
            ).all()
        }
        for name, code, department_type, prefix in DEFAULT_DEPARTMENTS:
            if code not in departments:
                department = Department(
                    id=demo_id(f"department-{code}"),
                    facility_id=facility.id,
                    name=name,
                    code=code,
                    type=department_type,
                    queue_prefix=prefix,
                )
                db.add(department)
                departments[code] = department

        patients = demo_patients(facility.id)
        db.add_all(patients)
        db.flush()

        opd = departments["OPD"]
        lab = departments["LAB"]
        pharmacy = departments["PHARM"]
        billing = departments["BILL"]
        theatre = departments["THR"]

        visit_specs = [
            ("visit-1", patients[0], opd, "Routine consultation", "OPD"),
            ("visit-2", patients[1], lab, "Blood test follow-up", "LAB"),
            ("visit-3", patients[2], pharmacy, "Prescription collection", "PHARM"),
            ("visit-4", patients[3], theatre, "Pre-operative assessment", "THR"),
        ]
        visits: dict[str, Visit] = {}
        for index, (key, patient, department, reason, prefix) in enumerate(visit_specs, 1):
            visit = Visit(
                id=demo_id(key),
                facility_id=facility.id,
                patient_id=patient.id,
                department_id=department.id,
                visit_number=f"DEMO-V{index:04d}",
                visit_date=now - timedelta(minutes=index * 8),
                reason=reason,
                expected_payment_method=patient.usual_payment_method,
                status="waiting",
            )
            visits[key] = visit
            db.add(visit)
            db.add(
                QueueEntry(
                    id=demo_id(f"queue-{index}"),
                    facility_id=facility.id,
                    visit_id=visit.id,
                    department_id=department.id,
                    queue_number=f"{prefix}-D{index:02d}",
                    queue_date=now.date(),
                    priority="urgent" if index == 2 else "routine",
                    status="waiting",
                    arrived_at=visit.visit_date,
                )
            )

        db.add(
            TriageRecord(
                id=demo_id("triage-1"),
                facility_id=facility.id,
                visit_id=visits["visit-1"].id,
                temperature=36.8,
                pulse=76,
                respiratory_rate=16,
                systolic=118,
                diastolic=76,
                spo2=99,
                weight=62.0,
                height=165.0,
                bmi=22.8,
                pain_score=1,
                priority="routine",
                notes="Synthetic test data only.",
                recorded_by="Synthetic test nurse",
            )
        )

        db.add(
            Appointment(
                id=demo_id("appointment-1"),
                facility_id=facility.id,
                patient_id=patients[0].id,
                department_id=opd.id,
                starts_at=now + timedelta(hours=2),
                ends_at=now + timedelta(hours=2, minutes=30),
                appointment_type="review",
                clinician="Dr. Susan Nakato",
                reason="Follow-up consultation",
                notes="Synthetic test appointment.",
                status="confirmed",
            )
        )

        stock = MedicationStockItem(
            id=demo_id("stock-1"),
            facility_id=facility.id,
            name="Paracetamol (test stock)",
            strength="500 mg",
            form="tablet",
            unit="tablet",
            quantity_on_hand=48,
            reorder_level=10,
            unit_price=Decimal("100.00"),
            active=True,
        )
        db.add(stock)
        db.add(
            MedicationOrder(
                id=demo_id("medication-order-1"),
                facility_id=facility.id,
                patient_id=patients[2].id,
                stock_item_id=stock.id,
                dosage="1 tablet",
                frequency="Three times daily",
                duration="3 days",
                quantity=9,
                instructions="Synthetic test only; not a real prescription.",
                status="requested",
                prescribed_by="synthetic-test-clinician",
            )
        )
        db.add(
            LaboratoryOrder(
                id=demo_id("lab-order-1"),
                facility_id=facility.id,
                patient_id=patients[1].id,
                test_name="Full blood count (test order)",
                specimen="Simulated blood specimen",
                priority="urgent",
                clinical_notes="Synthetic workflow test only; no real results.",
                status="requested",
                ordered_by="synthetic-test-clinician",
            )
        )

        invoice = BillingInvoice(
            id=demo_id("invoice-1"),
            facility_id=facility.id,
            patient_id=patients[0].id,
            invoice_number="DEMO-INV-0001",
            description="Consultation charge (test)",
            total_amount=Decimal("25000.00"),
            status="partially_paid",
            created_by="synthetic-test-billing",
        )
        db.add(invoice)
        db.add(
            BillingPayment(
                id=demo_id("payment-1"),
                facility_id=facility.id,
                invoice_id=invoice.id,
                amount=Decimal("10000.00"),
                method="mobile_money",
                reference="DEMO-REF-0001",
                recorded_by="synthetic-test-cashier",
            )
        )
        db.add(
            TheatreProcedure(
                id=demo_id("procedure-1"),
                facility_id=facility.id,
                patient_id=patients[3].id,
                procedure_name="Minor outpatient procedure (test)",
                scheduled_at=now + timedelta(days=1),
                lead_clinician="Dr. Susan Nakato",
                status="scheduled",
                notes="Synthetic workflow test only; no real procedure.",
                created_by="synthetic-test-theatre",
            )
        )
        db.commit()
        return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed synthetic IMARA-CARE workflow data in a local SQLite database."
    )
    parser.add_argument(
        "--confirm-demo-data",
        action="store_true",
        help="Confirm that synthetic test records should be added or refreshed.",
    )
    parser.add_argument(
        "--refresh-demo-data",
        action="store_true",
        help="Refresh seeded patient details and descriptive text without resetting workflow state.",
    )
    args = parser.parse_args()
    if args.refresh_demo_data and not args.confirm_demo_data:
        parser.error("--refresh-demo-data also requires --confirm-demo-data.")
    if not args.confirm_demo_data:
        parser.error("Pass --confirm-demo-data to add or refresh synthetic test records.")
    require_local_development_database()
    seeded = seed_demo_data(refresh_existing=args.refresh_demo_data)
    if seeded:
        print("Synthetic test data seeded.")
    elif args.refresh_demo_data:
        print("Synthetic test patient details refreshed; workflow state preserved.")
    else:
        print("Synthetic test data already exists; no changes made.")


if __name__ == "__main__":
    main()
