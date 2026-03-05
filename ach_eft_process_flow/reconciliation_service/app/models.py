from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    trace_number: Mapped[str] = mapped_column(String(128), nullable=False)
    payer_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(16), default="CREDIT")
    source_queue: Mapped[str] = mapped_column(String(64), nullable=False)
    claims_json: Mapped[str] = mapped_column(String(2048), default="[]")


class ReconciliationResult(Base):
    __tablename__ = "reconciliation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(256), default="")
