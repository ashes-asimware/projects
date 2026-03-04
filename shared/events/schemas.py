from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ServiceEvent(BaseModel):
    event_type: str
    source_service: str
    payload: dict
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
