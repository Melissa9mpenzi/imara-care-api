from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SupportRequestCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: Literal["access", "account", "workflow", "technical", "other"]
    subject: str = Field(min_length=3, max_length=120)
    message: str = Field(min_length=10, max_length=2000)


class SupportRequestStatusUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved"]
