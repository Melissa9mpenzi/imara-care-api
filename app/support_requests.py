from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuditEvent, Facility, SupportRequest
from app.support_schemas import SupportRequestCreate, SupportRequestStatusUpdate


router = APIRouter(prefix="/api/v1/support", tags=["support"])
SUPPORT_MANAGERS = {"admin", "facility_admin"}
email_adapter = TypeAdapter(EmailStr)


def _facility_id(db: Session) -> str:
    facility = db.scalar(select(Facility).where(Facility.code == settings.facility_code))
    if facility is None:
        raise HTTPException(status_code=503, detail="Facility setup is incomplete.")
    return facility.id


def _summary(ticket: SupportRequest) -> dict:
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "requester_id": ticket.requester_id,
        "requester_role": ticket.requester_role,
        "requester_name": ticket.requester_name,
        "requester_email": ticket.requester_email,
        "category": ticket.category,
        "subject": ticket.subject,
        "message": ticket.message,
        "status": ticket.status,
        "created_at": ticket.created_at,
        "updated_at": ticket.updated_at,
    }


@router.get("/requests")
def list_support_requests(
    request: Request,
    status_filter: str = Query(
        default="all",
        alias="status",
        pattern="^(all|open|in_progress|resolved)$",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    staff = request.state.staff_user
    facility_id = _facility_id(db)
    query = select(SupportRequest).where(
        SupportRequest.facility_id == facility_id
    )
    if staff["role"] not in SUPPORT_MANAGERS:
        query = query.where(SupportRequest.requester_id == staff["id"])
    if status_filter != "all":
        query = query.where(SupportRequest.status == status_filter)
    tickets = db.scalars(
        query.order_by(SupportRequest.created_at.desc()).limit(limit)
    ).all()
    return [_summary(ticket) for ticket in tickets]


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_support_request(
    payload: SupportRequestCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    staff = request.state.staff_user
    requester_name = staff.get("name")
    requester_email = staff.get("email")
    if not isinstance(requester_name, str) or not requester_name.strip():
        raise HTTPException(
            status_code=401,
            detail="Refresh your session before submitting a support request.",
        )
    if not isinstance(requester_email, str):
        raise HTTPException(
            status_code=401,
            detail="Refresh your session before submitting a support request.",
        )
    try:
        requester_email = str(email_adapter.validate_python(requester_email))
    except ValidationError as error:
        raise HTTPException(
            status_code=401,
            detail="Refresh your session before submitting a support request.",
        ) from error

    facility_id = _facility_id(db)
    ticket = SupportRequest(
        id=str(uuid4()),
        facility_id=facility_id,
        ticket_number=f"SUP-{datetime.now(timezone.utc):%Y%m%d}-{uuid4().hex[:8].upper()}",
        requester_id=staff["id"],
        requester_role=staff["role"],
        requester_name=requester_name.strip(),
        requester_email=requester_email,
        category=payload.category,
        subject=payload.subject,
        message=payload.message,
    )
    db.add(ticket)
    db.add(
        AuditEvent(
            facility_id=facility_id,
            actor=staff["id"],
            action="support.request_created",
            entity_type="support_request",
            entity_id=ticket.id,
            details={"category": ticket.category},
        )
    )
    db.commit()
    db.refresh(ticket)
    return _summary(ticket)


@router.patch("/requests/{request_id}")
def update_support_request_status(
    request_id: str,
    payload: SupportRequestStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    staff = request.state.staff_user
    if staff["role"] not in SUPPORT_MANAGERS:
        raise HTTPException(
            status_code=403,
            detail="Only facility administrators can update support requests.",
        )

    facility_id = _facility_id(db)
    ticket = db.scalar(
        select(SupportRequest).where(
            SupportRequest.id == request_id,
            SupportRequest.facility_id == facility_id,
        )
    )
    if ticket is None:
        raise HTTPException(status_code=404, detail="Support request not found.")

    previous_status = ticket.status
    ticket.status = payload.status
    ticket.updated_by = staff["id"]
    ticket.updated_at = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            facility_id=facility_id,
            actor=staff["id"],
            action="support.request_status_changed",
            entity_type="support_request",
            entity_id=ticket.id,
            details={"from": previous_status, "to": ticket.status},
        )
    )
    db.commit()
    db.refresh(ticket)
    return _summary(ticket)
