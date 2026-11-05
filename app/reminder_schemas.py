from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator


RepeatFrequency = Literal["none", "daily", "weekdays", "weekly", "monthly", "custom"]
ReminderPriority = Literal["normal", "high"]
ReminderLinkType = Literal["patient", "visit", "order", "invoice", "page"]


class ReminderCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    note: str | None = Field(default=None, max_length=500)
    link_type: ReminderLinkType | None = None
    link_id: str | None = Field(default=None, max_length=128)
    due_at: datetime
    timezone: str = Field(default="Africa/Kampala", min_length=1, max_length=64)
    repeat_frequency: RepeatFrequency = "none"
    repeat_interval: int = Field(default=1, ge=1, le=365)
    repeat_until: datetime | None = None
    alert_offsets: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=5)
    priority: ReminderPriority = "normal"

    @model_validator(mode="after")
    def validate_reminder(self):
        if self.due_at.tzinfo is None or self.due_at.utcoffset() is None:
            raise ValueError("Reminder date and time must include a timezone.")
        if self.repeat_until is not None:
            if self.repeat_until.tzinfo is None or self.repeat_until.utcoffset() is None:
                raise ValueError("Repeat end date must include a timezone.")
            if self.repeat_until <= self.due_at:
                raise ValueError("Repeat end date must be after the reminder date.")
        if self.repeat_frequency == "none" and self.repeat_until is not None:
            raise ValueError("A repeat end date requires a repeating reminder.")
        if 0 not in self.alert_offsets:
            raise ValueError("Alert offsets must include the reminder due time (0 minutes).")
        if any(offset < 0 or offset > 525600 for offset in self.alert_offsets):
            raise ValueError("Alert offsets must be between 0 and 525600 minutes.")
        if len(set(self.alert_offsets)) != len(self.alert_offsets):
            raise ValueError("Alert offsets cannot contain duplicates.")
        if (self.link_type is None) != (self.link_id is None):
            raise ValueError("Choose both a link type and link ID, or neither.")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError("Choose a valid IANA timezone.") from error
        return self


class ReminderAction(BaseModel):
    action: Literal["done", "cancel", "snooze"]
    snooze_until: datetime | None = None

    @model_validator(mode="after")
    def validate_snooze(self):
        if self.action == "snooze":
            if self.snooze_until is None or self.snooze_until.tzinfo is None:
                raise ValueError("Snoozing requires a date and time with a timezone.")
        elif self.snooze_until is not None:
            raise ValueError("Only snooze actions accept a snooze date.")
        return self


class NotificationReadRequest(BaseModel):
    notification_ids: list[str] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_ids(self):
        if self.notification_ids is not None and not self.notification_ids:
            raise ValueError("Provide at least one notification ID, or omit the list to mark all read.")
        return self
