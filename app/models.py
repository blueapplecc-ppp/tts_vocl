from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import BigInteger, Integer, String, Text, TIMESTAMP, ForeignKey, SmallInteger, UniqueConstraint
from sqlalchemy.sql import func

Base = declarative_base()


class TtsUser(Base):
    __tablename__ = 'tts_users'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    unified_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)


class TtsText(Base):
    __tablename__ = 'tts_texts'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tts_users.id'), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    oss_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)


class TtsAudio(Base):
    __tablename__ = 'tts_audios'
    __table_args__ = (
        UniqueConstraint('oss_object_key', name='uq_tts_audios_oss_object_key'),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    text_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tts_texts.id'), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tts_users.id'), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    oss_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)


class TtsDownload(Base):
    __tablename__ = 'tts_downloads'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audio_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('tts_audios.id'), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey('tts_users.id'), nullable=True)
    downloaded_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)


class TtsSystemConfig(Base):
    __tablename__ = 'tts_system_config'

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(String(128), nullable=False)
    config_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    created_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), nullable=False)
    updated_at: Mapped[str] = mapped_column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)


# Session helpers

def get_session():
    from flask import current_app
    return current_app.config['DATABASE_SESSION']()
