from sqlalchemy import Boolean, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class EFTReceipt(Base):
    __tablename__ = "eft_receipts"
    __table_args__ = (
        UniqueConstraint("trace_number", "payer_id", "provider_id", "amount_cents", name="uq_eft_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_number: Mapped[str] = mapped_column(String(64), nullable=False)
    payer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    claims: Mapped[list] = mapped_column(JSON, default=list)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)


class RemittanceReceipt(Base):
    __tablename__ = "remittance_receipts"
    __table_args__ = (
        UniqueConstraint("trace_number", "payer_id", "provider_id", "amount_cents", name="uq_remit_match"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_number: Mapped[str] = mapped_column(String(64), nullable=False)
    payer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    claims: Mapped[list] = mapped_column(JSON, default=list)
    matched: Mapped[bool] = mapped_column(Boolean, default=False)
