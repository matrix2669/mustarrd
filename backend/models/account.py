from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


DEFAULT_CATCHUP_RESOLUTION_MODE = "auto"


class XtreamAccount(Base):
    __tablename__ = "xtream_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    server_url: Mapped[str] = mapped_column(String(500))
    username: Mapped[str] = mapped_column(String(255))
    password: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    catchup_days: Mapped[int] = mapped_column(Integer, default=7)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_epg_backfill_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Cached account info from server
    max_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_connections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    catchup_resolution_mode: Mapped[str] = mapped_column(String(32), default=DEFAULT_CATCHUP_RESOLUTION_MODE)
    catchup_fallback_offset_minutes: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "server_url": self.server_url,
            "username": self.username,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "last_epg_backfill_at": self.last_epg_backfill_at.isoformat() if self.last_epg_backfill_at else None,
            "max_connections": self.max_connections,
            "active_connections": self.active_connections,
            "expiration_date": self.expiration_date.isoformat() if self.expiration_date else None,
            "catchup_resolution_mode": self.catchup_resolution_mode or DEFAULT_CATCHUP_RESOLUTION_MODE,
            "catchup_fallback_offset_minutes": int(self.catchup_fallback_offset_minutes or 0),
        }
