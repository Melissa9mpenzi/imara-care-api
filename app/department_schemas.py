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


class StockReceive(BaseModel):
    quantity: int = Field(gt=0, le=1_000_000)
    reference: str | None = Field(default=None, max_length=240)


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
