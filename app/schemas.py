from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


PaymentMethod = Literal["cash", "insurance", "mobile_money", "bank_transfer", "other"]
Priority = Literal["routine", "urgent", "emergency"]


class PatientCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    other_names: str | None = Field(default=None, max_length=120)
    sex: Literal["female", "male", "other", "not_specified"]
    date_of_birth: date | None = None
    estimated_age: int | None = Field(default=None, ge=0, le=125)
    phone: str | None = Field(default=None, max_length=32)
    alt_phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    national_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=240)
    next_of_kin_name: str | None = Field(default=None, max_length=160)
    next_of_kin_relationship: str | None = Field(default=None, max_length=80)
    next_of_kin_phone: str | None = Field(default=None, max_length=32)
    usual_payment_method: PaymentMethod = "cash"
    allergies: list[str] = Field(default_factory=list, max_length=20)
    sms_consent: bool = False

    @model_validator(mode="after")
    def require_date_or_age(self):
        if self.date_of_birth is None and self.estimated_age is None:
            raise ValueError("Provide a date of birth or an estimated age.")
        return self


class PatientUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    other_names: str | None = Field(default=None, max_length=120)
    sex: Literal["female", "male", "other", "not_specified"] | None = None
    date_of_birth: date | None = None
    estimated_age: int | None = Field(default=None, ge=0, le=125)
    phone: str | None = Field(default=None, max_length=32)
    alt_phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    national_id: str | None = Field(default=None, max_length=64)
    address: str | None = Field(default=None, max_length=240)
    next_of_kin_name: str | None = Field(default=None, max_length=160)
    next_of_kin_relationship: str | None = Field(default=None, max_length=80)
    next_of_kin_phone: str | None = Field(default=None, max_length=32)
    usual_payment_method: PaymentMethod | None = None
    allergies: list[str] | None = Field(default=None, max_length=20)
    sms_consent: bool | None = None
    status: Literal["active", "inactive"] | None = None


class PatientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_number: str
    first_name: str
    last_name: str
    other_names: str | None
    sex: str
    date_of_birth: date | None
    estimated_age: int | None
    phone: str | None
    email: str | None
    address: str | None
    usual_payment_method: str
    allergies: list[str]
    sms_consent: bool
    status: str
    created_at: datetime


class PatientDetail(PatientRead):
    alt_phone: str | None
    national_id: str | None
    next_of_kin_name: str | None
    next_of_kin_relationship: str | None
    next_of_kin_phone: str | None
    updated_at: datetime


class AppointmentCreate(BaseModel):
    patient_id: str
    department_id: str
    starts_at: datetime
    ends_at: datetime
    appointment_type: Literal["new", "review", "procedure", "antenatal", "physiotherapy"] = "new"
    clinician: str | None = Field(default=None, max_length=120)
    reason: str = Field(min_length=1, max_length=240)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def valid_time_range(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Appointment end time must be after its start time.")
        return self


class CheckInCreate(BaseModel):
    patient_id: str
    department_id: str
    reason: str = Field(min_length=1, max_length=240)
    expected_payment_method: PaymentMethod = "cash"
    priority: Priority = "routine"


class TriageCreate(BaseModel):
    temperature: float | None = Field(default=None, ge=25, le=45)
    pulse: int | None = Field(default=None, ge=0, le=300)
    respiratory_rate: int | None = Field(default=None, ge=0, le=100)
    systolic: int | None = Field(default=None, ge=0, le=300)
    diastolic: int | None = Field(default=None, ge=0, le=200)
    spo2: int | None = Field(default=None, ge=0, le=100)
    weight: float | None = Field(default=None, gt=0, le=500)
    height: float | None = Field(default=None, gt=0, le=260)
    pain_score: int | None = Field(default=None, ge=0, le=10)
    blood_sugar: float | None = Field(default=None, ge=0, le=100)
    priority: Priority = "routine"
    notes: str | None = Field(default=None, max_length=2000)
    recorded_by: str = Field(default="Triage Nurse", min_length=1, max_length=120)


class AppointmentStatusUpdate(BaseModel):
    status: Literal["confirmed", "cancelled", "no_show"]
    cancellation_reason: str | None = Field(default=None, max_length=240)
