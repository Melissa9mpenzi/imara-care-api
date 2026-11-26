from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class StockItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    strength: str = Field(min_length=1, max_length=80)
    form: str = Field(min_length=1, max_length=80)
    unit: str = Field(min_length=1, max_length=40)
    quantity_on_hand: int = Field(default=0, ge=0, le=1_000_000)
    reorder_level: int = Field(default=0, ge=0, le=1_000_000)
    unit_price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=12, decimal_places=2)
    batch_number: str | None = Field(default=None, min_length=1, max_length=100)
    expires_on: date | None = None
    reference: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def require_batch_for_opening_stock(self) -> "StockItemCreate":
        if self.quantity_on_hand and (not self.batch_number or not self.expires_on):
            raise ValueError("Batch number and expiry date are required for opening stock.")
        if self.quantity_on_hand and not self.reference:
            raise ValueError("A stock receipt reference is required for opening stock.")
        if self.batch_number and not self.expires_on:
            raise ValueError("An expiry date is required when a batch number is provided.")
        if self.expires_on and self.expires_on < date.today():
            raise ValueError("Expired stock cannot be received.")
        for field_name in ("batch_number", "reference"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = value.strip()
                if not normalized:
                    raise ValueError(f"{field_name.replace('_', ' ').capitalize()} cannot be blank.")
                setattr(self, field_name, normalized)
        return self


class StockReceive(BaseModel):
    quantity: int = Field(gt=0, le=1_000_000)
    batch_number: str = Field(min_length=1, max_length=100)
    expires_on: date
    reference: str = Field(min_length=1, max_length=240)

    @field_validator("batch_number", "reference")
    @classmethod
    def require_nonblank_receipt_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized

    @field_validator("expires_on")
    @classmethod
    def reject_expired_stock(cls, value: date) -> date:
        if value < date.today():
            raise ValueError("Expired stock cannot be received.")
        return value


class MedicationOrderCreate(BaseModel):
    patient_id: str
    stock_item_id: str
    dosage: str = Field(min_length=1, max_length=160)
    frequency: str = Field(min_length=1, max_length=160)
    duration: str | None = Field(default=None, max_length=100)
    quantity: int = Field(gt=0, le=1_000_000)
    instructions: str | None = Field(default=None, max_length=2000)


class LaboratoryOrderCreate(BaseModel):
    patient_id: str
    test_name: str = Field(min_length=1, max_length=160)
    specimen: str = Field(min_length=1, max_length=100)
    priority: Literal["routine", "urgent", "emergency"] = "routine"
    clinical_notes: str | None = Field(default=None, max_length=2000)


class LaboratoryResultCreate(BaseModel):
    result: str = Field(min_length=1, max_length=10000)


class LaboratorySampleStatusUpdate(BaseModel):
    status: Literal["collected", "processing", "rejected"]


class LaboratoryResultReviewCreate(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)


class InvoiceLineItemCreate(BaseModel):
    description: str = Field(min_length=1, max_length=240)
    unit: str = Field(default="service", min_length=1, max_length=40)
    quantity: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    unit_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    @field_validator("description", "unit")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def require_positive_line_amount(self) -> "InvoiceLineItemCreate":
        amount = (self.quantity * self.unit_price).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        if amount <= 0 or amount > Decimal("9999999999.99"):
            raise ValueError("Line amount must be between 0.01 and 9999999999.99.")
        return self


class InvoiceCreate(BaseModel):
    patient_id: str
    description: str | None = Field(default=None, min_length=1, max_length=240)
    total_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
    )
    items: list[InvoiceLineItemCreate] = Field(default_factory=list, max_length=50)
    bill_to_name: str | None = Field(default=None, max_length=160)
    bill_to_phone: str | None = Field(default=None, max_length=32)
    payer_type: Literal["self_pay", "insurance", "other"] = "self_pay"
    insurer_name: str | None = Field(default=None, max_length=160)
    payer_reference: str | None = Field(default=None, max_length=80)
    service_date: date | None = None
    due_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("description")
    @classmethod
    def normalize_invoice_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Description cannot be blank.")
        return normalized

    @model_validator(mode="after")
    def require_invoice_amount(self) -> "InvoiceCreate":
        if not self.items and (not self.description or self.total_amount is None):
            raise ValueError(
                "Provide itemized charges or a description and total amount."
            )
        if self.items and self.total_amount is not None:
            total = sum(
                (
                    (item.quantity * item.unit_price).quantize(
                        Decimal("0.01"),
                        rounding=ROUND_HALF_UP,
                    )
                    for item in self.items
                ),
                Decimal("0.00"),
            )
            if total > Decimal("9999999999.99"):
                raise ValueError("Invoice total is too large.")
            if self.total_amount != total:
                raise ValueError("Invoice total must match the itemized charges.")
        elif self.total_amount and self.total_amount > Decimal("9999999999.99"):
            raise ValueError("Invoice total is too large.")
        return self


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: Literal["cash", "insurance", "mobile_money", "bank_transfer", "other"]
    reference: str | None = Field(default=None, max_length=120)

    @field_validator("reference")
    @classmethod
    def normalize_payment_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class InsuranceClaimCreate(BaseModel):
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("notes")
    @classmethod
    def normalize_claim_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class InsuranceClaimUpdate(BaseModel):
    status: Literal["submitted", "approved", "denied", "paid"]
    external_claim_reference: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("external_claim_reference", "notes")
    @classmethod
    def normalize_optional_claim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TheatreProcedureCreate(BaseModel):
    patient_id: str
    procedure_name: str = Field(min_length=1, max_length=160)
    scheduled_at: datetime
    lead_clinician: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("scheduled_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Scheduled time must include a timezone.")
        return value


class TheatreProcedureUpdate(BaseModel):
    status: Literal["in_progress", "completed", "cancelled"]
    notes: str | None = Field(default=None, max_length=4000)
