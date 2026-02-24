"""Pydantic models for user activity tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict

from app.models.common import UserID

ACTIVITY_TYPES = Literal["view", "comment", "rate"]


class UserActivity(BaseModel):
    """Internal representation of a user activity row.

    Field names match DB column names (snake_case) exactly — no aliases needed.
    """

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    userid: UserID
    day: str
    activity_type: ACTIVITY_TYPES
    activity_id: UUID
    activity_timestamp: datetime


class UserActivityResponse(BaseModel):
    """API response representation for a single user activity item."""

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    userId: UserID = Field(..., validation_alias="userid")
    activityType: str = Field(..., validation_alias="activity_type")
    activityId: UUID = Field(..., validation_alias="activity_id")
    activityTimestamp: datetime = Field(..., validation_alias="activity_timestamp")


__all__ = [
    "ACTIVITY_TYPES",
    "UserActivity",
    "UserActivityResponse",
]
