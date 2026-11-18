from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class InvoiceCreate(BaseModel):
    patient_id: str
    description: str = Field(min_length=1, max_length=240)
    total_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


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
