from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class EPGProgram(Base):
    __tablename__ = "epg_programs"
    __table_args__ = (
        Index("ix_epg_programs_account_channel_start", "account_id", "channel_id", "start_time"),
        Index("ux_epg_programs_account_epg_id", "account_id", "epg_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("xtream_accounts.id"))

    # Channel info
    channel_id: Mapped[str] = mapped_column(String(100))  # Xtream stream_id
    channel_name: Mapped[str] = mapped_column(String(255))
    xmltv_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Program info
    epg_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    start_timestamp: Mapped[int] = mapped_column(Integer)
    stop_timestamp: Mapped[int] = mapped_column(Integer)
    provider_start: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_stop: Mapped[str | None] = mapped_column(String(255), nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    has_archive: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
