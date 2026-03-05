from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ProcessingRecord(Base):
    __tablename__ = "ach_processing_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    raw_data: Mapped[str | None] = mapped_column(Text, nullable=True)
