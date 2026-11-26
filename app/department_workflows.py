from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.config import settings
from app.database import get_db
from app.department_schemas import (
    InvoiceCreate,
    InsuranceClaimCreate,
    InsuranceClaimUpdate,
    LaboratoryOrderCreate,
    LaboratoryResultReviewCreate,
    LaboratoryResultCreate,
    LaboratorySampleStatusUpdate,
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
    BillingInvoiceDetails,
    BillingInvoiceLine,
    BillingPaymentReceipt,
    Department,
    BillingPayment,
    Facility,
    LaboratoryOrder,
    LaboratoryResultReview,
    LaboratorySample,
    MedicationOrder,
    MedicationStockBatch,
    MedicationStockItem,
    MedicationStockMovement,
    InsuranceClaim,
    Patient,
    QueueEntry,
    TheatreProcedure,
    Visit,
    utc_now,
)
from app.security import require_department_module
from app.spreadsheet_imports import read_spreadsheet_rows

router = APIRouter(prefix="/api/v1", tags=["department workflows"])

STOCK_IMPORT_ALIASES = {
    "name": "name",
    "medicine": "name",
    "medicine_name": "name",
    "drug_name": "name",
    "strength": "strength",
    "form": "form",
    "formulation": "form",
    "unit": "unit",
    "stock_unit": "unit",
    "unit_of_measure": "unit",
    "quantity_on_hand": "quantity_on_hand",
    "quantity": "quantity_on_hand",
    "stock_quantity": "quantity_on_hand",
    "opening_quantity": "quantity_on_hand",
    "reorder_level": "reorder_level",
    "reorder_at": "reorder_level",
    "unit_price": "unit_price",
    "price": "unit_price",
    "batch_number": "batch_number",
    "lot_number": "batch_number",
    "expires_on": "expires_on",
    "expiry_date": "expires_on",
    "expiration_date": "expires_on",
}


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
        "phone": patient.phone,
    }


def _department_patient_ids(facility_id: str, department_id: str, code: str):
    if code in {"BILL", "PHARM"}:
        return select(Patient.id).where(Patient.facility_id == facility_id)
    patient_ids = select(Visit.patient_id).where(
        Visit.facility_id == facility_id,
    )
    patient_ids = patient_ids.where(Visit.department_id == department_id)
    department_orders = {
        "PHARM": MedicationOrder,
        "LAB": LaboratoryOrder,
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
    today = datetime.now(timezone.utc).date()
    batches = sorted(item.batches, key=lambda batch: (batch.expires_on, batch.received_at))
    available_quantity = sum(
        batch.quantity_remaining
        for batch in batches
        if batch.expires_on >= today
    )
    expired_quantity = sum(
        batch.quantity_remaining
        for batch in batches
        if batch.expires_on < today
    )
    tracked_quantity = sum(batch.quantity_remaining for batch in batches)
    return {
        "id": item.id,
        "name": item.name,
        "strength": item.strength,
        "form": item.form,
        "unit": item.unit,
        "quantity_on_hand": item.quantity_on_hand,
        "available_quantity": available_quantity,
        "expired_quantity": expired_quantity,
        "untracked_quantity": max(item.quantity_on_hand - tracked_quantity, 0),
        "reorder_level": item.reorder_level,
        "unit_price": str(item.unit_price),
        "low_stock": available_quantity <= item.reorder_level,
        "active": item.active,
        "batches": [
            {
                "batch_number": batch.batch_number,
                "expires_on": batch.expires_on.isoformat(),
                "quantity_remaining": batch.quantity_remaining,
                "expired": batch.expires_on < today,
            }
            for batch in batches
            if batch.quantity_remaining > 0
        ],
        "updated_at": item.updated_at.isoformat(),
    }


def record_stock_batch(
    db: Session,
    facility_id: str,
    item: MedicationStockItem,
    *,
    quantity: int,
    batch_number: str,
    expires_on: date,
    reference: str,
    staff_id: str,
) -> None:
    if expires_on < datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="Expired stock cannot be received.")
    batch_number = batch_number.strip()
    receipt_reference = reference.strip()
    batch = db.scalar(
        select(MedicationStockBatch)
        .where(
            MedicationStockBatch.facility_id == facility_id,
            MedicationStockBatch.stock_item_id == item.id,
            func.lower(MedicationStockBatch.batch_number) == batch_number.casefold(),
        )
        .with_for_update()
    )
    if batch is not None:
        if batch.expires_on != expires_on:
            raise HTTPException(
                status_code=409,
                detail="This batch number is already recorded with a different expiry date.",
            )
        batch.quantity_received += quantity
        batch.quantity_remaining += quantity
    else:
        db.add(
            MedicationStockBatch(
                facility_id=facility_id,
                stock_item_id=item.id,
                batch_number=batch_number,
                expires_on=expires_on,
                quantity_received=quantity,
                quantity_remaining=quantity,
                received_by=staff_id,
            )
        )
    db.add(
        MedicationStockMovement(
            facility_id=facility_id,
            stock_item_id=item.id,
            movement_type="received",
            quantity=quantity,
            reference=receipt_reference,
            created_by=staff_id,
        )
    )


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
    sample_status = order.sample.status if order.sample else "awaiting_collection"
    review_status = (
        "reviewed"
        if order.review
        else "awaiting_review"
        if order.status == "resulted"
        else "not_ready"
    )
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
        "sample_status": sample_status,
        "sample_collected_at": (
            order.sample.collected_at.isoformat()
            if order.sample and order.sample.collected_at
            else None
        ),
        "review_status": review_status,
        "reviewed_by": order.review.reviewed_by if order.review else None,
        "reviewed_at": (
            order.review.reviewed_at.isoformat()
            if order.review
            else None
        ),
        "review_notes": order.review.notes if order.review else None,
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
        "items": [
            {
                "id": item.id,
                "description": item.description,
                "unit": item.unit,
                "quantity": str(item.quantity),
                "unit_price": str(item.unit_price),
                "amount": str(item.amount),
            }
            for item in invoice.items
        ],
        "billing_details": (
            {
                "bill_to_name": invoice.billing_details.bill_to_name,
                "bill_to_phone": invoice.billing_details.bill_to_phone,
                "payer_type": invoice.billing_details.payer_type,
                "insurer_name": invoice.billing_details.insurer_name,
                "payer_reference": invoice.billing_details.payer_reference,
                "service_date": (
                    invoice.billing_details.service_date.isoformat()
                    if invoice.billing_details.service_date
                    else None
                ),
                "due_date": (
                    invoice.billing_details.due_date.isoformat()
                    if invoice.billing_details.due_date
                    else None
                ),
                "notes": invoice.billing_details.notes,
            }
            if invoice.billing_details
            else None
        ),
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
                "receipt_number": (
                    payment.receipt.receipt_number if payment.receipt else None
                ),
            }
            for payment in (payments or [])
        ],
        "insurance_claim": (
            insurance_claim_summary(invoice.insurance_claim)
            if invoice.insurance_claim
            else None
        ),
        "created_by": invoice.created_by,
        "created_at": invoice.created_at.isoformat(),
    }


def insurance_claim_summary(claim: InsuranceClaim) -> dict:
    return {
        "id": claim.id,
        "claim_number": claim.claim_number,
        "status": claim.status,
        "insurer_name": claim.invoice.billing_details.insurer_name,
        "payer_reference": claim.invoice.billing_details.payer_reference,
        "external_claim_reference": claim.external_claim_reference,
        "notes": claim.notes,
        "created_by": claim.created_by,
        "updated_by": claim.updated_by,
        "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "resolved_at": claim.resolved_at.isoformat() if claim.resolved_at else None,
        "created_at": claim.created_at.isoformat(),
        "updated_at": claim.updated_at.isoformat(),
    }


def invoice_line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return (quantity * unit_price).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


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
        .options(selectinload(MedicationStockItem.batches))
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
        record_stock_batch(
            db,
            facility_id,
            item,
            quantity=payload.quantity_on_hand,
            batch_number=payload.batch_number or "",
            expires_on=payload.expires_on or date.min,
            reference=payload.reference or "",
            staff_id=staff["id"],
        )
    add_audit(
        db, facility_id, staff["id"], "pharmacy.stock_created",
        "medication_stock_item", item.id,
    )
    db.commit()
    db.refresh(item)
    return stock_summary(item)


def normalize_stock_import_row(row: dict, reference: str) -> StockItemCreate:
    values = {
        key: value.strip() if isinstance(value, str) else value
        for key, value in row.items()
        if key != "_row_number"
    }
    values["reference"] = f"Bulk stock import: {reference}"
    return StockItemCreate.model_validate(values)


def stock_import_error(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        for item in error.errors(include_input=False)
    )


@router.post("/pharmacy/stock/import")
def import_pharmacy_stock(
    request: Request,
    file: UploadFile = File(...),
    reference: str = Form(..., min_length=1, max_length=200),
    preview: bool = Query(default=False),
    confirm_restock_matches: bool = Form(default=False),
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "PHARM", {"pharmacy", "pharmacist"})
    reference = reference.strip()
    if not reference:
        raise HTTPException(status_code=422, detail="A stock receipt reference is required.")
    rows = read_spreadsheet_rows(
        file,
        aliases=STOCK_IMPORT_ALIASES,
        required_columns={
            "name",
            "strength",
            "form",
            "unit",
            "quantity_on_hand",
            "batch_number",
            "expires_on",
        },
    )
    receipt_reference = f"Bulk stock import: {reference}"
    facility_query = select(Facility).where(Facility.code == settings.facility_code)
    if not preview:
        facility_query = facility_query.with_for_update()
    facility = db.scalar(facility_query)
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")

    previous_receipt = db.scalar(
        select(MedicationStockMovement.id)
        .where(
            MedicationStockMovement.facility_id == facility.id,
            func.lower(MedicationStockMovement.reference)
            == receipt_reference.casefold(),
        )
        .limit(1)
    )
    if previous_receipt is not None:
        raise HTTPException(
            status_code=409,
            detail="This stock receipt reference has already been used. Use a new reference to prevent double-counting.",
        )

    existing_items = db.scalars(
        select(MedicationStockItem).where(
            MedicationStockItem.facility_id == facility.id,
        )
    ).all()
    existing_batches = db.scalars(
        select(MedicationStockBatch).where(
            MedicationStockBatch.facility_id == facility.id,
        )
    ).all()
    items_by_key: dict[tuple[str, str, str], list[MedicationStockItem]] = {}
    for item in existing_items:
        key = (item.name.strip().casefold(), item.strength.strip().casefold(), item.form.strip().casefold())
        items_by_key.setdefault(key, []).append(item)
    batch_expiries = {
        (batch.stock_item_id, batch.batch_number.strip().casefold()): batch.expires_on
        for batch in existing_batches
    }

    seen_file_keys: set[tuple[str, str, str, str]] = set()
    new_product_keys: set[tuple[str, str, str]] = set()
    parsed_rows: list[
        tuple[int, StockItemCreate, str, MedicationStockItem | None, tuple[str, str, str]]
    ] = []
    results: list[dict] = []
    restock_count = 0
    new_count = 0

    for row_number, raw_row in rows:
        try:
            payload = normalize_stock_import_row(raw_row, reference)
        except ValidationError as error:
            results.append({
                "row": row_number,
                "display": "Medicine row",
                "status": "invalid",
                "message": stock_import_error(error),
            })
            continue

        display = f"{payload.name} {payload.strength} ({payload.form})"
        if payload.quantity_on_hand < 1:
            results.append({
                "row": row_number,
                "display": display,
                "status": "invalid",
                "message": "Quantity must be greater than zero for a stock import.",
            })
            continue

        key = (payload.name.casefold(), payload.strength.casefold(), payload.form.casefold())
        batch_key = (*key, (payload.batch_number or "").casefold())
        if batch_key in seen_file_keys:
            results.append({
                "row": row_number,
                "display": display,
                "status": "duplicate",
                "message": "This medicine batch appears more than once in the file; only the first row is considered.",
            })
            continue
        seen_file_keys.add(batch_key)

        matches = items_by_key.get(key, [])
        if len(matches) > 1:
            results.append({
                "row": row_number,
                "display": display,
                "status": "invalid",
                "message": "More than one stock item matches this medicine; resolve the existing inventory first.",
            })
            continue
        existing = matches[0] if matches else None
        if existing is not None and not existing.active:
            results.append({
                "row": row_number,
                "display": display,
                "status": "duplicate",
                "message": "An inactive stock item already matches this medicine; it was not changed.",
            })
            continue
        if existing is not None and existing.unit.strip().casefold() != payload.unit.casefold():
            results.append({
                "row": row_number,
                "display": display,
                "status": "invalid",
                "message": "The stock unit differs from the existing item; no stock was changed.",
            })
            continue
        if existing is not None:
            batch_expiry = batch_expiries.get(
                (existing.id, (payload.batch_number or "").casefold())
            )
            if batch_expiry is not None and batch_expiry != payload.expires_on:
                results.append({
                    "row": row_number,
                    "display": display,
                    "status": "invalid",
                    "message": "This batch number is already recorded with a different expiry date.",
                })
                continue

        if existing is not None:
            restock_count += 1
            status_label = "restock"
            message = (
                f"Will add {payload.quantity_on_hand} {payload.unit} to existing stock; "
                "price and reorder level will not change."
            )
        else:
            if key not in new_product_keys:
                new_count += 1
                new_product_keys.add(key)
            status_label = "new"
            message = "A new stock item and expiry-tracked batch will be created."
        parsed_rows.append((row_number, payload, status_label, existing, key))
        results.append({
            "row": row_number,
            "display": display,
            "status": status_label,
            "message": message,
        })

    if preview:
        return {
            "preview": True,
            "total_rows": len(rows),
            "created": 0,
            "restocked": 0,
            "new": new_count,
            "restock": restock_count,
            "duplicates": sum(row["status"] == "duplicate" for row in results),
            "invalid": sum(row["status"] == "invalid" for row in results),
            "rows": results,
        }
    if restock_count and not confirm_restock_matches:
        raise HTTPException(
            status_code=400,
            detail="Confirm that matching stock quantities should be added before importing.",
        )

    committed_results: list[dict] = []
    try:
        new_items_by_key: dict[tuple[str, str, str], MedicationStockItem] = {}
        for row_number, payload, row_status, existing, item_key in parsed_rows:
            if row_status == "new":
                item = new_items_by_key.get(item_key)
                is_new_item = item is None
                if item is None:
                    item = MedicationStockItem(
                        facility_id=facility.id,
                        name=payload.name,
                        strength=payload.strength,
                        form=payload.form,
                        unit=payload.unit,
                        quantity_on_hand=0,
                        reorder_level=payload.reorder_level,
                        unit_price=payload.unit_price,
                    )
                    db.add(item)
                    db.flush()
                    new_items_by_key[item_key] = item
                item.quantity_on_hand += payload.quantity_on_hand
                item.updated_at = utc_now()
                record_stock_batch(
                    db,
                    facility.id,
                    item,
                    quantity=payload.quantity_on_hand,
                    batch_number=payload.batch_number or "",
                    expires_on=payload.expires_on or date.min,
                    reference=receipt_reference,
                    staff_id=staff["id"],
                )
                if is_new_item:
                    add_audit(
                        db,
                        facility.id,
                        staff["id"],
                        "pharmacy.stock_created",
                        "medication_stock_item",
                        item.id,
                        {"source": "spreadsheet_import", "reference": reference},
                    )
                    status_label = "created"
                else:
                    status_label = "imported"
            else:
                if existing is None:
                    raise HTTPException(
                        status_code=409,
                        detail="A matching stock item changed during import. Preview the file again.",
                    )
                item = db.scalar(
                    select(MedicationStockItem)
                    .where(
                        MedicationStockItem.id == existing.id,
                        MedicationStockItem.facility_id == facility.id,
                        MedicationStockItem.active.is_(True),
                    )
                    .with_for_update()
                )
                if item is None:
                    raise HTTPException(
                        status_code=409,
                        detail="A matching stock item changed during import. Preview the file again.",
                    )
                item.quantity_on_hand += payload.quantity_on_hand
                item.updated_at = utc_now()
                record_stock_batch(
                    db,
                    facility.id,
                    item,
                    quantity=payload.quantity_on_hand,
                    batch_number=payload.batch_number or "",
                    expires_on=payload.expires_on or date.min,
                    reference=receipt_reference,
                    staff_id=staff["id"],
                )
                add_audit(
                    db,
                    facility.id,
                    staff["id"],
                    "pharmacy.stock_received",
                    "medication_stock_item",
                    item.id,
                    {
                        "quantity": payload.quantity_on_hand,
                        "source": "spreadsheet_import",
                        "reference": reference,
                    },
                )
                status_label = "restocked"
            committed_results.append({
                "row": row_number,
                "display": f"{payload.name} {payload.strength} ({payload.form})",
                "status": status_label,
                "message": "Stock item imported.",
            })
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The stock import could not be committed. No rows were saved; preview the file and try again.",
        ) from error

    committed_by_row = {result["row"]: result for result in committed_results}
    final_results = [
        committed_by_row.get(result["row"], result)
        for result in results
    ]
    return {
        "preview": False,
        "total_rows": len(rows),
        "created": sum(result["status"] == "created" for result in committed_results),
        "restocked": sum(result["status"] == "restocked" for result in committed_results),
        "new": 0,
        "restock": 0,
        "duplicates": sum(row["status"] == "duplicate" for row in final_results),
        "invalid": sum(row["status"] == "invalid" for row in final_results),
        "rows": final_results,
    }


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
    record_stock_batch(
        db,
        facility_id,
        item,
        quantity=payload.quantity,
        batch_number=payload.batch_number,
        expires_on=payload.expires_on,
        reference=payload.reference,
        staff_id=staff["id"],
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
    today = datetime.now(timezone.utc).date()
    batches = db.scalars(
        select(MedicationStockBatch)
        .where(
            MedicationStockBatch.facility_id == facility_id,
            MedicationStockBatch.stock_item_id == order.stock_item_id,
            MedicationStockBatch.quantity_remaining > 0,
            MedicationStockBatch.expires_on >= today,
        )
        .order_by(MedicationStockBatch.expires_on, MedicationStockBatch.received_at)
        .with_for_update()
    ).all()
    available_quantity = sum(batch.quantity_remaining for batch in batches)
    if available_quantity < order.quantity:
        raise HTTPException(
            status_code=409,
            detail="There is not enough unexpired, batch-tracked stock to dispense this order.",
        )
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
    quantity_to_dispense = order.quantity
    for batch in batches:
        taken = min(batch.quantity_remaining, quantity_to_dispense)
        batch.quantity_remaining -= taken
        quantity_to_dispense -= taken
        if quantity_to_dispense == 0:
            break
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
        .options(
            joinedload(LaboratoryOrder.patient),
            joinedload(LaboratoryOrder.sample),
            joinedload(LaboratoryOrder.review),
        )
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
    db.add(
        LaboratorySample(
            facility_id=facility_id,
            order_id=order.id,
            updated_by=staff["id"],
        )
    )
    add_audit(
        db, facility_id, staff["id"], "laboratory.order_created",
        "laboratory_order", order.id,
    )
    db.commit()
    order = db.scalar(
        select(LaboratoryOrder)
        .options(
            joinedload(LaboratoryOrder.patient),
            joinedload(LaboratoryOrder.sample),
            joinedload(LaboratoryOrder.review),
        )
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
    if order.sample is None or order.sample.status not in {"collected", "processing"}:
        raise HTTPException(
            status_code=409,
            detail="Record sample collection before entering a result.",
        )
    order.result = payload.result.strip()
    order.status = "resulted"
    order.resulted_by = staff["id"]
    order.resulted_at = utc_now()
    order.sample.status = "resulted"
    order.sample.updated_by = staff["id"]
    order.sample.updated_at = utc_now()
    add_audit(
        db, facility_id, staff["id"], "laboratory.result_recorded",
        "laboratory_order", order.id,
    )
    db.commit()
    order = db.scalar(
        select(LaboratoryOrder)
        .options(
            joinedload(LaboratoryOrder.patient),
            joinedload(LaboratoryOrder.sample),
            joinedload(LaboratoryOrder.review),
        )
        .where(LaboratoryOrder.id == order_id)
    )
    return laboratory_order_summary(order)


@router.patch("/laboratory/orders/{order_id}/sample")
def update_laboratory_sample_status(
    order_id: str,
    payload: LaboratorySampleStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "LAB", {"laboratory"})
    facility_id = facility_id_for(db)
    order = db.scalar(
        select(LaboratoryOrder)
        .options(joinedload(LaboratoryOrder.sample))
        .where(
            LaboratoryOrder.id == order_id,
            LaboratoryOrder.facility_id == facility_id,
        )
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Laboratory order not found.")
    if order.status != "requested":
        raise HTTPException(
            status_code=409,
            detail="Sample status cannot change after a result is entered.",
        )
    sample = order.sample
    if sample is None:
        sample = LaboratorySample(
            facility_id=facility_id,
            order_id=order.id,
            status="awaiting_collection",
            updated_by=staff["id"],
        )
        db.add(sample)
        db.flush()
    allowed_transitions = {
        "awaiting_collection": {"collected", "rejected"},
        "collected": {"processing", "rejected"},
        "processing": {"rejected"},
    }
    if payload.status not in allowed_transitions.get(sample.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Sample cannot move from {sample.status} to {payload.status}.",
        )
    sample.status = payload.status
    sample.updated_by = staff["id"]
    sample.updated_at = utc_now()
    if payload.status == "collected":
        sample.collected_by = staff["id"]
        sample.collected_at = sample.updated_at
    add_audit(
        db,
        facility_id,
        staff["id"],
        "laboratory.sample_status_updated",
        "laboratory_order",
        order.id,
        {"status": payload.status},
    )
    db.commit()
    order = db.scalar(
        select(LaboratoryOrder)
        .options(
            joinedload(LaboratoryOrder.patient),
            joinedload(LaboratoryOrder.sample),
            joinedload(LaboratoryOrder.review),
        )
        .where(LaboratoryOrder.id == order_id)
    )
    return laboratory_order_summary(order)


@router.post("/laboratory/orders/{order_id}/review")
def review_laboratory_result(
    order_id: str,
    payload: LaboratoryResultReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "LAB", {"laboratory"}, allow_clinical=True)
    if staff.get("role") not in {
        "clinician",
        "admin",
        "facility_admin",
        "medical_director",
    }:
        raise HTTPException(
            status_code=403,
            detail="Only a clinician or facility administrator can review a result.",
        )
    facility_id = facility_id_for(db)
    order = db.scalar(
        select(LaboratoryOrder)
        .options(
            joinedload(LaboratoryOrder.patient),
            joinedload(LaboratoryOrder.sample),
            joinedload(LaboratoryOrder.review),
        )
        .where(
            LaboratoryOrder.id == order_id,
            LaboratoryOrder.facility_id == facility_id,
        )
        .with_for_update()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Laboratory order not found.")
    if order.status != "resulted" or not order.result:
        raise HTTPException(
            status_code=409,
            detail="Only a recorded laboratory result can be reviewed.",
        )
    if order.review is not None:
        raise HTTPException(status_code=409, detail="This laboratory result has already been reviewed.")
    review = LaboratoryResultReview(
        facility_id=facility_id,
        order_id=order.id,
        reviewed_by=staff["id"],
        notes=payload.notes.strip() if payload.notes and payload.notes.strip() else None,
    )
    order.review = review
    db.add(review)
    add_audit(
        db,
        facility_id,
        staff["id"],
        "laboratory.result_reviewed",
        "laboratory_order",
        order.id,
        {"notes_recorded": bool(review.notes)},
    )
    db.commit()
    order = db.scalar(
        select(LaboratoryOrder)
        .options(
            joinedload(LaboratoryOrder.patient),
            joinedload(LaboratoryOrder.sample),
            joinedload(LaboratoryOrder.review),
        )
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
        .options(
            joinedload(BillingInvoice.patient),
            selectinload(BillingInvoice.items),
            joinedload(BillingInvoice.billing_details),
            joinedload(BillingInvoice.insurance_claim),
        )
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
        .options(selectinload(BillingPayment.receipt))
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


@router.post(
    "/billing/invoices/{invoice_id}/claims",
    status_code=status.HTTP_201_CREATED,
)
def create_insurance_claim(
    invoice_id: str,
    payload: InsuranceClaimCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "BILL", {"billing"})
    facility_id = facility_id_for(db)
    invoice = db.scalar(
        select(BillingInvoice)
        .options(joinedload(BillingInvoice.billing_details))
        .where(
            BillingInvoice.id == invoice_id,
            BillingInvoice.facility_id == facility_id,
        )
        .with_for_update()
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if not invoice.billing_details or invoice.billing_details.payer_type != "insurance":
        raise HTTPException(status_code=409, detail="Only insurance invoices can have claims.")
    if db.scalar(
        select(InsuranceClaim.id).where(InsuranceClaim.invoice_id == invoice.id)
    ):
        raise HTTPException(status_code=409, detail="A claim already exists for this invoice.")

    claim = InsuranceClaim(
        facility_id=facility_id,
        invoice_id=invoice.id,
        claim_number=f"CLM-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
        notes=payload.notes,
        created_by=staff["id"],
    )
    db.add(claim)
    db.flush()
    add_audit(
        db,
        facility_id,
        staff["id"],
        "billing.claim_created",
        "insurance_claim",
        claim.id,
        {"invoice_id": invoice.id, "claim_number": claim.claim_number},
    )
    db.commit()
    claim = db.scalar(
        select(InsuranceClaim)
        .options(
            joinedload(InsuranceClaim.invoice).joinedload(BillingInvoice.billing_details)
        )
        .where(InsuranceClaim.id == claim.id)
    )
    return insurance_claim_summary(claim)


@router.patch("/billing/claims/{claim_id}")
def update_insurance_claim(
    claim_id: str,
    payload: InsuranceClaimUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "BILL", {"billing"})
    facility_id = facility_id_for(db)
    claim = db.scalar(
        select(InsuranceClaim)
        .options(joinedload(InsuranceClaim.invoice))
        .where(
            InsuranceClaim.id == claim_id,
            InsuranceClaim.facility_id == facility_id,
        )
        .with_for_update()
    )
    if claim is None:
        raise HTTPException(status_code=404, detail="Insurance claim not found.")
    transitions = {
        "draft": {"submitted"},
        "submitted": {"approved", "denied"},
        "denied": {"submitted"},
        "approved": {"paid"},
    }
    if payload.status not in transitions.get(claim.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Claim cannot move from {claim.status} to {payload.status}.",
        )
    if payload.status == "paid":
        insurance_payment = db.scalar(
            select(BillingPayment.id)
            .where(
                BillingPayment.invoice_id == claim.invoice_id,
                BillingPayment.facility_id == facility_id,
                BillingPayment.method == "insurance",
            )
            .limit(1)
        )
        if insurance_payment is None:
            raise HTTPException(
                status_code=409,
                detail="Record an insurer payment before marking this claim paid.",
            )
    previous_status = claim.status
    claim.status = payload.status
    if payload.external_claim_reference is not None:
        claim.external_claim_reference = payload.external_claim_reference
    if payload.notes is not None:
        claim.notes = payload.notes
    claim.updated_by = staff["id"]
    now = datetime.now(timezone.utc)
    if payload.status == "submitted":
        claim.submitted_at = now
        claim.resolved_at = None
    else:
        claim.resolved_at = now
    add_audit(
        db,
        facility_id,
        staff["id"],
        "billing.claim_status_updated",
        "insurance_claim",
        claim.id,
        {"from": previous_status, "to": claim.status},
    )
    db.commit()
    claim = db.scalar(
        select(InsuranceClaim)
        .options(
            joinedload(InsuranceClaim.invoice).joinedload(BillingInvoice.billing_details)
        )
        .where(InsuranceClaim.id == claim.id)
    )
    return insurance_claim_summary(claim)


@router.post("/billing/invoices", status_code=status.HTTP_201_CREATED)
def create_billing_invoice(
    payload: InvoiceCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    staff = staff_for(request, "BILL", {"billing"})
    facility_id = facility_id_for(db)
    patient = require_patient(db, facility_id, payload.patient_id)
    if payload.items:
        line_amounts = [
            invoice_line_amount(item.quantity, item.unit_price)
            for item in payload.items
        ]
        total_amount = sum(line_amounts, Decimal("0.00"))
        description = payload.description or (
            payload.items[0].description
            if len(payload.items) == 1
            else f"{payload.items[0].description} + {len(payload.items) - 1} more"
        )
    elif payload.total_amount is not None and payload.description:
        line_amounts = []
        total_amount = payload.total_amount
        description = payload.description.strip()
    else:
        raise HTTPException(
            status_code=422,
            detail="Provide itemized charges or a description and total amount.",
        )
    invoice = BillingInvoice(
        facility_id=facility_id,
        patient_id=patient.id,
        invoice_number=f"INV-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
        description=description[:240],
        total_amount=total_amount,
        created_by=staff["id"],
        items=[
            BillingInvoiceLine(
                position=index,
                description=item.description,
                unit=item.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=line_amounts[index],
            )
            for index, item in enumerate(payload.items)
        ],
        billing_details=BillingInvoiceDetails(
            bill_to_name=payload.bill_to_name.strip()
            if payload.bill_to_name and payload.bill_to_name.strip()
            else None,
            bill_to_phone=payload.bill_to_phone.strip()
            if payload.bill_to_phone and payload.bill_to_phone.strip()
            else None,
            payer_type=payload.payer_type,
            insurer_name=payload.insurer_name.strip()
            if payload.insurer_name and payload.insurer_name.strip()
            else None,
            payer_reference=payload.payer_reference.strip()
            if payload.payer_reference and payload.payer_reference.strip()
            else None,
            service_date=payload.service_date,
            due_date=payload.due_date,
            notes=payload.notes.strip() if payload.notes and payload.notes.strip() else None,
        ),
    )
    db.add(invoice)
    db.flush()
    add_audit(
        db, facility_id, staff["id"], "billing.invoice_created",
        "billing_invoice",
        invoice.id,
        {
            "amount": str(invoice.total_amount),
            "line_count": len(payload.items),
        },
    )
    db.commit()
    invoice = db.scalar(
        select(BillingInvoice)
        .options(
            joinedload(BillingInvoice.patient),
            selectinload(BillingInvoice.items),
            joinedload(BillingInvoice.billing_details),
            joinedload(BillingInvoice.insurance_claim),
        )
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
        receipt=BillingPaymentReceipt(
            facility_id=facility_id,
            receipt_number=f"RCT-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
            issued_by=staff["id"],
        ),
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
        .options(
            joinedload(BillingInvoice.patient),
            selectinload(BillingInvoice.items),
            joinedload(BillingInvoice.billing_details),
            joinedload(BillingInvoice.insurance_claim),
        )
        .where(BillingInvoice.id == invoice_id)
    )
    saved_payments = db.scalars(
        select(BillingPayment)
        .options(selectinload(BillingPayment.receipt))
        .where(BillingPayment.invoice_id == invoice.id)
        .order_by(BillingPayment.paid_at)
    ).all()
    return invoice_summary(invoice, paid_amount, saved_payments)


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
