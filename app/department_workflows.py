from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.department_schemas import (
    InvoiceCreate,
    LaboratoryOrderCreate,
    LaboratoryResultCreate,
    MedicationOrderCreate,
    PaymentCreate,
    StockItemCreate,
    StockReceive,
    TheatreProcedureCreate,
    TheatreProcedureUpdate,
)
from app.models import (
    AuditEvent,
    BillingInvoice,
    Department,
    BillingPayment,
    Facility,
    LaboratoryOrder,
    MedicationOrder,
    MedicationStockItem,
    MedicationStockMovement,
    Patient,
    QueueEntry,
    TheatreProcedure,
    Visit,
    utc_now,
)
from app.security import require_department_module

router = APIRouter(prefix="/api/v1", tags=["department workflows"])


def facility_id_for(db: Session) -> str:
    facility = db.scalar(select(Facility).where(Facility.code == settings.facility_code))
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")
    return facility.id


def staff_for(request: Request, code: str, roles: set[str], *, allow_clinical: bool = False) -> dict:
    return require_department_module(
        request, code, roles, allow_clinical=allow_clinical
    )


def require_patient(db: Session, facility_id: str, patient_id: str) -> Patient:
    patient = db.scalar(
        select(Patient).where(
            Patient.id == patient_id,
            Patient.facility_id == facility_id,
        )
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


def add_audit(
    db: Session,
    facility_id: str,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
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


def patient_summary(patient: Patient) -> dict:
    return {
        "id": patient.id,
        "patient_number": patient.patient_number,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "other_names": patient.other_names,
    }


def _department_patient_ids(facility_id: str, department_id: str, code: str):
    patient_ids = select(Visit.patient_id).where(
        Visit.facility_id == facility_id,
    )
    if code != "BILL":
        patient_ids = patient_ids.where(Visit.department_id == department_id)
    department_orders = {
        "PHARM": MedicationOrder,
        "LAB": LaboratoryOrder,
        "BILL": BillingInvoice,
        "THR": TheatreProcedure,
    }
    order_model = department_orders.get(code)
    if order_model:
        patient_ids = patient_ids.union(
            select(order_model.patient_id).where(
                order_model.facility_id == facility_id
            )
        )
    return patient_ids


def stock_summary(item: MedicationStockItem) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "strength": item.strength,
        "form": item.form,
        "unit": item.unit,
        "quantity_on_hand": item.quantity_on_hand,
        "reorder_level": item.reorder_level,
        "unit_price": str(item.unit_price),
        "low_stock": item.quantity_on_hand <= item.reorder_level,
        "active": item.active,
        "updated_at": item.updated_at.isoformat(),
    }


def medication_order_summary(order: MedicationOrder) -> dict:
    return {
        "id": order.id,
        "patient": patient_summary(order.patient),
        "medication": (
            f"{order.stock_item.name} {order.stock_item.strength} "
            f"({order.stock_item.form})"
        ),
        "stock_item_id": order.stock_item_id,
        "dosage": order.dosage,
        "frequency": order.frequency,
        "duration": order.duration,
        "quantity": order.quantity,
        "instructions": order.instructions,
        "status": order.status,
        "prescribed_by": order.prescribed_by,
        "dispensed_by": order.dispensed_by,
        "created_at": order.created_at.isoformat(),
        "dispensed_at": order.dispensed_at.isoformat() if order.dispensed_at else None,
    }


def laboratory_order_summary(order: LaboratoryOrder) -> dict:
    return {
        "id": order.id,
        "patient": patient_summary(order.patient),
        "test_name": order.test_name,
        "specimen": order.specimen,
        "priority": order.priority,
        "clinical_notes": order.clinical_notes,
        "status": order.status,
        "result": order.result,
        "ordered_by": order.ordered_by,
        "resulted_by": order.resulted_by,
        "created_at": order.created_at.isoformat(),
        "resulted_at": order.resulted_at.isoformat() if order.resulted_at else None,
    }


def invoice_summary(
    invoice: BillingInvoice,
    paid_amount: Decimal = Decimal("0.00"),
    payments: list[BillingPayment] | None = None,
) -> dict:
    total = invoice.total_amount
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "patient": patient_summary(invoice.patient),
        "description": invoice.description,
        "total_amount": str(total),
        "paid_amount": str(paid_amount),
        "balance": str(total - paid_amount),
        "status": invoice.status,
        "payments": [
            {
                "id": payment.id,
                "amount": str(payment.amount),
                "method": payment.method,
                "reference": payment.reference,
                "recorded_by": payment.recorded_by,
                "paid_at": payment.paid_at.isoformat(),
            }
            for payment in (payments or [])
        ],
        "created_by": invoice.created_by,
        "created_at": invoice.created_at.isoformat(),
    }


def theatre_procedure_summary(procedure: TheatreProcedure) -> dict:
    return {
        "id": procedure.id,
        "patient": patient_summary(procedure.patient),
        "procedure_name": procedure.procedure_name,
        "scheduled_at": procedure.scheduled_at.isoformat(),
        "lead_clinician": procedure.lead_clinician,
        "status": procedure.status,
        "notes": procedure.notes,
        "created_by": procedure.created_by,
        "created_at": procedure.created_at.isoformat(),
    }


@router.get("/pharmacy/stock")
def list_pharmacy_stock(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict]:
    staff_for(
        request,
        "PHARM",
        {"pharmacy", "pharmacist"},
        allow_clinical=True,
    )
    facility_id = facility_id_for(db)
    items = db.scalars(
        select(MedicationStockItem)
        .where(
            MedicationStockItem.facility_id == facility_id,
            MedicationStockItem.active.is_(True),
        )
        .order_by(MedicationStockItem.name)
    ).all()
    return [stock_summary(item) for item in items]


@router.get("/departments/patients")
def search_department_patients(
    request: Request,
    department_code: str,
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
) -> list[dict]:
    module_roles = {
        "PHARM": {"pharmacy", "pharmacist"},
        "LAB": {"laboratory"},
        "BILL": {"billing", "cashier"},
        "THR": {"theatre"},
    }
    if department_code not in module_roles:
        raise HTTPException(status_code=403, detail="This department has no active workspace.")
    staff_for(
        request,
        department_code,
        module_roles[department_code],
        allow_clinical=department_code in {"PHARM", "LAB", "THR"},
    )
    facility_id = facility_id_for(db)
    department = db.scalar(
        select(Department).where(
            Department.facility_id == facility_id,
            Department.code == department_code,
            Department.active.is_(True),
        )
    )
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found.")
    query = select(Patient).where(
        Patient.facility_id == facility_id,
        Patient.status == "active",
        Patient.id.in_(
            _department_patient_ids(facility_id, department.id, department_code)
        ),
    )
    search_term = q.strip()
    if search_term:
        pattern = f"%{search_term}%"
        query = query.where(
            or_(
                Patient.first_name.ilike(pattern),
                Patient.last_name.ilike(pattern),
                Patient.other_names.ilike(pattern),
                Patient.patient_number.ilike(pattern),
                Patient.phone.ilike(pattern),
            )
        )
    patients = db.scalars(
        query.order_by(Patient.last_name, Patient.first_name).limit(limit)
    ).all()
    return [
        {
            "id": patient.id,
            "patient_number": patient.patient_number,
            "first_name": patient.first_name,
            "last_name": patient.last_name,
            "other_names": patient.other_names,
            "phone": patient.phone,
        }
        for patient in patients
    ]


@router.get("/departments/queues")
def list_department_queue(
    request: Request,
    department_code: str,
    status_filter: str = Query(
        default="all",
        alias="status",
        pattern="^(all|waiting|in_service|completed|cancelled)$",
    ),
    db: Session = Depends(get_db),
) -> list[dict]:
    module_roles = {
        "PHARM": {"pharmacy", "pharmacist"},
        "LAB": {"laboratory"},
        "BILL": {"billing", "cashier"},
        "THR": {"theatre"},
    }
    if department_code not in module_roles:
        raise HTTPException(status_code=403, detail="This department has no active workspace.")
    staff_for(
        request,
        department_code,
        module_roles[department_code],
        allow_clinical=department_code in {"PHARM", "LAB", "THR"},
    )
    facility_id = facility_id_for(db)
    department = db.scalar(
        select(Department).where(
            Department.facility_id == facility_id,
            Department.code == department_code,
            Department.active.is_(True),
        )
    )
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found.")

    query = (
        select(QueueEntry)
        .options(
            joinedload(QueueEntry.visit).joinedload(Visit.patient),
            joinedload(QueueEntry.visit).joinedload(Visit.department),
            joinedload(QueueEntry.visit).joinedload(Visit.triage),
        )
        .where(
            QueueEntry.facility_id == facility_id,
            QueueEntry.department_id == department.id,
        )
    )
    if status_filter != "all":
        query = query.where(QueueEntry.status == status_filter)
    entries = db.scalars(
        query.order_by(QueueEntry.arrived_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": entry.id,
            "queue_number": entry.queue_number,
            "priority": entry.priority,
            "status": entry.status,
            "arrived_at": entry.arrived_at.isoformat(),
            "visit_id": entry.visit_id,
            "visit_number": entry.visit.visit_number,
            "reason": entry.visit.reason,
            "patient": patient_summary(entry.visit.patient),
        }
        for entry in entries
    ]


@router.post("/pharmacy/stock", status_code=status.HTTP_201_CREATED)
def create_pharmacy_stock(
    payload: StockItemCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "PHARM", {"pharmacy", "pharmacist"})
    facility_id = facility_id_for(db)
    item = MedicationStockItem(
        facility_id=facility_id,
        name=payload.name.strip(),
        strength=payload.strength.strip(),
        form=payload.form.strip(),
        unit=payload.unit.strip(),
        quantity_on_hand=payload.quantity_on_hand,
        reorder_level=payload.reorder_level,
        unit_price=payload.unit_price,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This medication strength and form already exist in stock.",
        ) from error
    if payload.quantity_on_hand:
        db.add(
            MedicationStockMovement(
                facility_id=facility_id,
                stock_item_id=item.id,
                movement_type="received",
                quantity=payload.quantity_on_hand,
                created_by=staff["id"],
            )
        )
    add_audit(
        db, facility_id, staff["id"], "pharmacy.stock_created",
        "medication_stock_item", item.id,
    )
    db.commit()
    db.refresh(item)
    return stock_summary(item)


@router.post("/pharmacy/stock/{item_id}/receive")
def receive_pharmacy_stock(
    item_id: str,
    payload: StockReceive,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "PHARM", {"pharmacy", "pharmacist"})
    facility_id = facility_id_for(db)
    item = db.scalar(
        select(MedicationStockItem)
        .where(
            MedicationStockItem.id == item_id,
            MedicationStockItem.facility_id == facility_id,
            MedicationStockItem.active.is_(True),
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Medication stock item not found.")
    item.quantity_on_hand += payload.quantity
    item.updated_at = utc_now()
    db.add(
        MedicationStockMovement(
            facility_id=facility_id,
            stock_item_id=item.id,
            movement_type="received",
            quantity=payload.quantity,
            reference=payload.reference,
            created_by=staff["id"],
        )
    )
    add_audit(
        db, facility_id, staff["id"], "pharmacy.stock_received",
        "medication_stock_item", item.id, {"quantity": payload.quantity},
    )
    db.commit()
    db.refresh(item)
    return stock_summary(item)


@router.get("/pharmacy/orders")
def list_pharmacy_orders(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict]:
    staff_for(
        request,
        "PHARM",
        {"pharmacy", "pharmacist"},
        allow_clinical=True,
    )
    facility_id = facility_id_for(db)
    orders = db.scalars(
        select(MedicationOrder)
        .options(joinedload(MedicationOrder.patient), joinedload(MedicationOrder.stock_item))
        .where(MedicationOrder.facility_id == facility_id)
        .order_by(MedicationOrder.created_at.desc())
        .limit(100)
    ).all()
    return [medication_order_summary(order) for order in orders]


@router.post("/pharmacy/orders", status_code=status.HTTP_201_CREATED)
def create_medication_order(
    payload: MedicationOrderCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(
        request,
        "PHARM",
        {"pharmacy", "pharmacist"},
        allow_clinical=True,
    )
    facility_id = facility_id_for(db)
    patient = require_patient(db, facility_id, payload.patient_id)
    item = db.scalar(
        select(MedicationStockItem).where(
            MedicationStockItem.id == payload.stock_item_id,
            MedicationStockItem.facility_id == facility_id,
            MedicationStockItem.active.is_(True),
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Medication stock item not found.")
    order = MedicationOrder(
        facility_id=facility_id,
        patient_id=patient.id,
        stock_item_id=item.id,
        dosage=payload.dosage.strip(),
        frequency=payload.frequency.strip(),
        duration=payload.duration,
        quantity=payload.quantity,
        instructions=payload.instructions,
        prescribed_by=staff["id"],
    )
    db.add(order)
    db.flush()
    add_audit(
        db, facility_id, staff["id"], "pharmacy.order_created",
        "medication_order", order.id,
    )
    db.commit()
    order = db.scalar(
        select(MedicationOrder)
        .options(joinedload(MedicationOrder.patient), joinedload(MedicationOrder.stock_item))
        .where(MedicationOrder.id == order.id)
    )
    return medication_order_summary(order)


@router.post("/pharmacy/orders/{order_id}/dispense")
def dispense_medication_order(
    order_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "PHARM", {"pharmacy", "pharmacist"})
    facility_id = facility_id_for(db)
    order = db.scalar(
        select(MedicationOrder)
        .where(
            MedicationOrder.id == order_id,
            MedicationOrder.facility_id == facility_id,
        )
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Medication order not found.")
    if order.status != "requested":
        raise HTTPException(status_code=409, detail="Only requested orders can be dispensed.")
    result = db.execute(
        update(MedicationStockItem)
        .where(
            MedicationStockItem.id == order.stock_item_id,
            MedicationStockItem.facility_id == facility_id,
            MedicationStockItem.active.is_(True),
            MedicationStockItem.quantity_on_hand >= order.quantity,
        )
        .values(
            quantity_on_hand=MedicationStockItem.quantity_on_hand - order.quantity,
            updated_at=utc_now(),
        )
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="There is not enough stock to dispense this order.",
        )
    order.status = "dispensed"
    order.dispensed_by = staff["id"]
    order.dispensed_at = utc_now()
    db.add(
        MedicationStockMovement(
            facility_id=facility_id,
            stock_item_id=order.stock_item_id,
            movement_type="dispensed",
            quantity=-order.quantity,
            reference=order.id,
            created_by=staff["id"],
        )
    )
    add_audit(
        db, facility_id, staff["id"], "pharmacy.order_dispensed",
        "medication_order", order.id, {"quantity": order.quantity},
    )
    db.commit()
    order = db.scalar(
        select(MedicationOrder)
        .options(joinedload(MedicationOrder.patient), joinedload(MedicationOrder.stock_item))
        .where(MedicationOrder.id == order_id)
    )
    return medication_order_summary(order)


@router.get("/laboratory/orders")
def list_laboratory_orders(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict]:
    staff_for(
        request,
        "LAB",
        {"laboratory"},
        allow_clinical=True,
    )
    facility_id = facility_id_for(db)
    orders = db.scalars(
        select(LaboratoryOrder)
        .options(joinedload(LaboratoryOrder.patient))
        .where(LaboratoryOrder.facility_id == facility_id)
        .order_by(LaboratoryOrder.created_at.desc())
        .limit(100)
    ).all()
    return [laboratory_order_summary(order) for order in orders]


@router.post("/laboratory/orders", status_code=status.HTTP_201_CREATED)
def create_laboratory_order(
    payload: LaboratoryOrderCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(
        request,
        "LAB",
        {"laboratory"},
        allow_clinical=True,
    )
    facility_id = facility_id_for(db)
    patient = require_patient(db, facility_id, payload.patient_id)
    order = LaboratoryOrder(
        facility_id=facility_id,
        patient_id=patient.id,
        test_name=payload.test_name.strip(),
        specimen=payload.specimen.strip(),
        priority=payload.priority,
        clinical_notes=payload.clinical_notes,
        ordered_by=staff["id"],
    )
    db.add(order)
    db.flush()
    add_audit(
        db, facility_id, staff["id"], "laboratory.order_created",
        "laboratory_order", order.id,
    )
    db.commit()
    order = db.scalar(
        select(LaboratoryOrder)
        .options(joinedload(LaboratoryOrder.patient))
        .where(LaboratoryOrder.id == order.id)
    )
    return laboratory_order_summary(order)


@router.post("/laboratory/orders/{order_id}/result")
def record_laboratory_result(
    order_id: str,
    payload: LaboratoryResultCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "LAB", {"laboratory"})
    facility_id = facility_id_for(db)
    order = db.scalar(
        select(LaboratoryOrder)
        .where(
            LaboratoryOrder.id == order_id,
            LaboratoryOrder.facility_id == facility_id,
        )
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Laboratory order not found.")
    if order.status != "requested":
        raise HTTPException(status_code=409, detail="Only requested tests can receive a result.")
    order.result = payload.result.strip()
    order.status = "resulted"
    order.resulted_by = staff["id"]
    order.resulted_at = utc_now()
    add_audit(
        db, facility_id, staff["id"], "laboratory.result_recorded",
        "laboratory_order", order.id,
    )
    db.commit()
    order = db.scalar(
        select(LaboratoryOrder)
        .options(joinedload(LaboratoryOrder.patient))
        .where(LaboratoryOrder.id == order_id)
    )
    return laboratory_order_summary(order)


@router.get("/billing/invoices")
def list_billing_invoices(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict]:
    staff_for(request, "BILL", {"billing", "cashier"})
    facility_id = facility_id_for(db)
    invoices = db.scalars(
        select(BillingInvoice)
        .options(joinedload(BillingInvoice.patient))
        .where(BillingInvoice.facility_id == facility_id)
        .order_by(BillingInvoice.created_at.desc())
        .limit(100)
    ).all()
    if not invoices:
        return []
    paid_rows = db.execute(
        select(BillingPayment.invoice_id, func.sum(BillingPayment.amount))
        .where(BillingPayment.invoice_id.in_([invoice.id for invoice in invoices]))
        .group_by(BillingPayment.invoice_id)
    ).all()
    paid_by_invoice = {invoice_id: amount for invoice_id, amount in paid_rows}
    payment_rows = db.scalars(
        select(BillingPayment)
        .where(BillingPayment.invoice_id.in_([invoice.id for invoice in invoices]))
        .order_by(BillingPayment.paid_at)
    ).all()
    payments_by_invoice: dict[str, list[BillingPayment]] = {}
    for payment in payment_rows:
        payments_by_invoice.setdefault(payment.invoice_id, []).append(payment)
    return [
        invoice_summary(
            invoice,
            paid_by_invoice.get(invoice.id, Decimal("0.00")),
            payments_by_invoice.get(invoice.id, []),
        )
        for invoice in invoices
    ]


@router.post("/billing/invoices", status_code=status.HTTP_201_CREATED)
def create_billing_invoice(
    payload: InvoiceCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "BILL", {"billing"})
    facility_id = facility_id_for(db)
    patient = require_patient(db, facility_id, payload.patient_id)
    invoice = BillingInvoice(
        facility_id=facility_id,
        patient_id=patient.id,
        invoice_number=f"INV-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
        description=payload.description.strip(),
        total_amount=payload.total_amount,
        created_by=staff["id"],
    )
    db.add(invoice)
    db.flush()
    add_audit(
        db, facility_id, staff["id"], "billing.invoice_created",
        "billing_invoice", invoice.id, {"amount": str(invoice.total_amount)},
    )
    db.commit()
    invoice = db.scalar(
        select(BillingInvoice)
        .options(joinedload(BillingInvoice.patient))
        .where(BillingInvoice.id == invoice.id)
    )
    return invoice_summary(invoice)


@router.post("/billing/invoices/{invoice_id}/payments", status_code=status.HTTP_201_CREATED)
def record_billing_payment(
    invoice_id: str,
    payload: PaymentCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "BILL", {"billing", "cashier"})
    facility_id = facility_id_for(db)
    invoice = db.scalar(
        select(BillingInvoice)
        .where(
            BillingInvoice.id == invoice_id,
            BillingInvoice.facility_id == facility_id,
        )
        .with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice.status == "void":
        raise HTTPException(status_code=409, detail="A void invoice cannot receive payments.")
    paid_amount = db.scalar(
        select(func.coalesce(func.sum(BillingPayment.amount), 0)).where(
            BillingPayment.invoice_id == invoice.id
        )
    ) or Decimal("0.00")
    if payload.amount > invoice.total_amount - paid_amount:
        raise HTTPException(status_code=409, detail="Payment exceeds the invoice balance.")
    payment = BillingPayment(
        facility_id=facility_id,
        invoice_id=invoice.id,
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        recorded_by=staff["id"],
    )
    db.add(payment)
    paid_amount += payload.amount
    invoice.status = "paid" if paid_amount == invoice.total_amount else "partially_paid"
    add_audit(
        db, facility_id, staff["id"], "billing.payment_recorded",
        "billing_invoice", invoice.id, {"amount": str(payload.amount)},
    )
    db.commit()
    invoice = db.scalar(
        select(BillingInvoice)
        .options(joinedload(BillingInvoice.patient))
        .where(BillingInvoice.id == invoice_id)
    )
    return invoice_summary(invoice, paid_amount)


@router.get("/theatre/procedures")
def list_theatre_procedures(
    request: Request,
    db: Session = Depends(get_db),
) -> list[dict]:
    staff_for(request, "THR", {"theatre"}, allow_clinical=True)
    facility_id = facility_id_for(db)
    procedures = db.scalars(
        select(TheatreProcedure)
        .options(joinedload(TheatreProcedure.patient))
        .where(TheatreProcedure.facility_id == facility_id)
        .order_by(TheatreProcedure.scheduled_at)
        .limit(100)
    ).all()
    return [theatre_procedure_summary(procedure) for procedure in procedures]


@router.post("/theatre/procedures", status_code=status.HTTP_201_CREATED)
def create_theatre_procedure(
    payload: TheatreProcedureCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "THR", {"theatre"}, allow_clinical=True)
    facility_id = facility_id_for(db)
    patient = require_patient(db, facility_id, payload.patient_id)
    procedure = TheatreProcedure(
        facility_id=facility_id,
        patient_id=patient.id,
        procedure_name=payload.procedure_name.strip(),
        scheduled_at=payload.scheduled_at,
        lead_clinician=payload.lead_clinician.strip(),
        notes=payload.notes,
        created_by=staff["id"],
    )
    db.add(procedure)
    db.flush()
    add_audit(
        db, facility_id, staff["id"], "theatre.procedure_scheduled",
        "theatre_procedure", procedure.id,
    )
    db.commit()
    procedure = db.scalar(
        select(TheatreProcedure)
        .options(joinedload(TheatreProcedure.patient))
        .where(TheatreProcedure.id == procedure.id)
    )
    return theatre_procedure_summary(procedure)


@router.patch("/theatre/procedures/{procedure_id}")
def update_theatre_procedure(
    procedure_id: str,
    payload: TheatreProcedureUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "THR", {"theatre"})
    facility_id = facility_id_for(db)
    procedure = db.scalar(
        select(TheatreProcedure)
        .where(
            TheatreProcedure.id == procedure_id,
            TheatreProcedure.facility_id == facility_id,
        )
        .with_for_update()
    )
    if procedure is None:
        raise HTTPException(status_code=404, detail="Theatre procedure not found.")
    valid_next_states = {
        "scheduled": {"in_progress", "cancelled"},
        "in_progress": {"completed"},
    }
    if payload.status not in valid_next_states.get(procedure.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"A {procedure.status} procedure cannot transition to {payload.status}.",
        )
    procedure.status = payload.status
    if payload.notes is not None:
        procedure.notes = payload.notes
    add_audit(
        db, facility_id, staff["id"], "theatre.procedure_status_changed",
        "theatre_procedure", procedure.id, {"status": payload.status},
    )
    db.commit()
    procedure = db.scalar(
        select(TheatreProcedure)
        .options(joinedload(TheatreProcedure.patient))
        .where(TheatreProcedure.id == procedure_id)
    )
    return theatre_procedure_summary(procedure)
