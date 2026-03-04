from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class JournalEntry(Base):
    """Immutable double-entry journal record. No update or delete operations are exposed."""

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_queue: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    lines: Mapped[list["JournalLine"]] = relationship(
        "JournalLine", back_populates="entry", cascade="all, delete-orphan"
    )


class JournalLine(Base):
    """Debit or credit line belonging to a JournalEntry."""

    __tablename__ = "journal_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    journal_entry_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("journal_entries.id"), nullable=False, index=True
    )
    line_type: Mapped[str] = mapped_column(String(8), nullable=False)  # DEBIT or CREDIT
    account_code: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    entry: Mapped["JournalEntry"] = relationship("JournalEntry", back_populates="lines")
