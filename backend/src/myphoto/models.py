from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # admin|viewer
    access_scope: Mapped[str] = mapped_column(String, nullable=False, default="lan_only")
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)
    last_login_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Gallery(Base):
    __tablename__ = "galleries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer, nullable=False)


class GalleryRoot(Base):
    __tablename__ = "gallery_roots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gallery_id: Mapped[int] = mapped_column(ForeignKey("galleries.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    absolute_path: Mapped[str] = mapped_column(String, nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_scan_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scan_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_scan_error: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (
        UniqueConstraint("gallery_id", "absolute_path", name="uq_root_path_per_gallery"),
    )


class Folder(Base):
    __tablename__ = "folders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("gallery_roots.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String, nullable=False)  # "" for root itself
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    descendant_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("root_id", "relative_path", name="uq_folder_path_per_root"),
        Index("ix_folder_root_parent", "root_id", "parent_id"),
    )


class Image(Base):
    __tablename__ = "images"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(ForeignKey("gallery_roots.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[int] = mapped_column(ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    ext: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha1: Mapped[str] = mapped_column(String, nullable=False)
    mtime: Mapped[int] = mapped_column(Integer, nullable=False)
    taken_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_raw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_at: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("root_id", "relative_path", name="uq_image_path_per_root"),
        Index("ix_image_folder_filename", "folder_id", "filename"),
        Index("ix_image_folder_taken", "folder_id", "taken_at"),
        Index("ix_image_sha1", "sha1"),
    )
