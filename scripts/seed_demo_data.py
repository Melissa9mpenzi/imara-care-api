import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

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


def seed_demo_data() -> bool:
    initialize_database()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with SessionLocal() as db:
        facility = db.scalar(
            select(Facility).where(Facility.code == settings.facility_code)
        )
        if facility is None:
            raise RuntimeError("The configured demo facility was not initialized.")
        if db.get(Patient, demo_id("patient-1")) is not None:
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

        patients = [
            Patient(
                id=demo_id("patient-1"),
                facility_id=facility.id,
                patient_number="DEMO-0001",
                first_name="Demo Amina",
                last_name="Sample",
                sex="female",
                date_of_birth=datetime(1992, 4, 12).date(),
                phone="+256700000001",
                usual_payment_method="cash",
                allergies=["Demo allergy - penicillin"],
                status="active",
            ),
            Patient(
                id=demo_id("patient-2"),
                facility_id=facility.id,
                patient_number="DEMO-0002",
                first_name="Demo Daniel",
                last_name="Example",
                sex="male",
                date_of_birth=datetime(1986, 9, 3).date(),
                phone="+256700000002",
                usual_payment_method="insurance",
                allergies=[],
                status="active",
            ),
            Patient(
                id=demo_id("patient-3"),
                facility_id=facility.id,
                patient_number="DEMO-0003",
                first_name="Demo Grace",
                last_name="Testcase",
                sex="female",
                date_of_birth=datetime(2001, 1, 21).date(),
                phone="+256700000003",
                usual_payment_method="mobile_money",
                allergies=[],
                status="active",
            ),
            Patient(
                id=demo_id("patient-4"),
                facility_id=facility.id,
                patient_number="DEMO-0004",
                first_name="Demo Peter",
                last_name="Fiction",
                sex="male",
                date_of_birth=datetime(1978, 6, 15).date(),
                phone="+256700000004",
                usual_payment_method="cash",
                allergies=[],
                status="active",
            ),
        ]
        db.add_all(patients)
        db.flush()

        opd = departments["OPD"]
        lab = departments["LAB"]
        pharmacy = departments["PHARM"]
        billing = departments["BILL"]
        theatre = departments["THR"]

        visit_specs = [
            ("visit-1", patients[0], opd, "DEMO - routine consultation", "OPD"),
            ("visit-2", patients[1], lab, "DEMO - blood test follow-up", "LAB"),
            ("visit-3", patients[2], pharmacy, "DEMO - prescription collection", "PHARM"),
            ("visit-4", patients[3], theatre, "DEMO - scheduled procedure", "THR"),
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
                notes="DEMO DATA ONLY",
                recorded_by="Demo Nurse",
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
                clinician="Demo Clinician",
                reason="DEMO - follow-up appointment",
                notes="Synthetic test appointment",
                status="confirmed",
            )
        )

        stock = MedicationStockItem(
            id=demo_id("stock-1"),
            facility_id=facility.id,
            name="Demo Paracetamol",
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
                instructions="DEMO DATA ONLY - do not use as a real prescription",
                status="requested",
                prescribed_by="demo-clinician",
            )
        )
        db.add(
            LaboratoryOrder(
                id=demo_id("lab-order-1"),
                facility_id=facility.id,
                patient_id=patients[1].id,
                test_name="Demo full blood count",
                specimen="Demo blood sample",
                priority="urgent",
                clinical_notes="Synthetic workflow test only",
                status="requested",
                ordered_by="demo-clinician",
            )
        )

        invoice = BillingInvoice(
            id=demo_id("invoice-1"),
            facility_id=facility.id,
            patient_id=patients[0].id,
            invoice_number="DEMO-INV-0001",
            description="DEMO - consultation charge",
            total_amount=Decimal("25000.00"),
            status="partially_paid",
            created_by="demo-billing",
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
                recorded_by="demo-cashier",
            )
        )
        db.add(
            TheatreProcedure(
                id=demo_id("procedure-1"),
                facility_id=facility.id,
                patient_id=patients[3].id,
                procedure_name="DEMO - sample procedure",
                scheduled_at=now + timedelta(days=1),
                lead_clinician="Demo Clinician",
                status="scheduled",
                notes="Synthetic workflow test only",
                created_by="demo-theatre",
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
        help="Confirm that synthetic, non-clinical test records should be added.",
    )
    args = parser.parse_args()
    if not args.confirm_demo_data:
        parser.error("Pass --confirm-demo-data to add clearly labelled synthetic test records.")
    require_local_development_database()
    seeded = seed_demo_data()
    print(
        "Synthetic demo data seeded."
        if seeded
        else "Synthetic demo data already exists; no changes made."
    )


if __name__ == "__main__":
    main()
