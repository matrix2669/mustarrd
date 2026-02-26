from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="download_only")
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    show_future_programs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    password_reset_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "username": self.username,
            "display_name": self.display_name,
            "status": self.status,
            "show_future_programs": self.show_future_programs,
            "password_reset_required": bool(self.password_reset_required),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="ux_user_identities_provider_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    provider_subject: Mapped[str] = mapped_column(String(255), index=True)
    provider_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "provider_subject": self.provider_subject,
            "provider_username": self.provider_username,
            "provider_email": self.provider_email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserSetupToken(Base):
    __tablename__ = "user_setup_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PlexServer(Base):
    __tablename__ = "plex_servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    connection_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resource_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    machine_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    library_section_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_allow_all_server_users: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "base_url": self.base_url,
            "connection_uri": self.connection_uri,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "machine_identifier": self.machine_identifier,
            "library_section_ids": self.library_section_ids,
            "auto_allow_all_server_users": self.auto_allow_all_server_users,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
