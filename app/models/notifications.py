from datetime import datetime
from typing import TYPE_CHECKING, Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


if TYPE_CHECKING:
    from app.models.jobs import Job


NotificationDestinationType = Literal[
    "recommendation",
    "application_activity",
    "scan_summary",
]


class NotificationDestination(Base):
    __tablename__ = "notification_destinations"
    __table_args__ = (
        UniqueConstraint("type", name="uq_notification_destinations_type"),
        CheckConstraint(
            "type IN ('recommendation', 'application_activity', 'scan_summary')",
            name="ck_notification_destinations_type",
        ),
        Index("ix_notification_destinations_enabled", "is_enabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(120))
    telegram_chat_id: Mapped[str] = mapped_column(String(32), default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    logs: Mapped[list["NotificationLog"]] = relationship(
        back_populates="destination",
        cascade="all, delete-orphan",
    )


class NotificationLog(Base):
    __tablename__ = "notification_log"
    __table_args__ = (
        UniqueConstraint(
            "destination_id",
            "event_key",
            name="uq_notification_log_destination_event",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_notification_log_status",
        ),
        Index("ix_notification_log_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    destination_id: Mapped[int] = mapped_column(
        ForeignKey("notification_destinations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scan_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    destination: Mapped[NotificationDestination] = relationship(back_populates="logs")
    job: Mapped["Job | None"] = relationship()
