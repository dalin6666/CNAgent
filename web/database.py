from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import Base


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self._ensure_sqlite_directory()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def _ensure_sqlite_directory(self) -> None:
        prefix = "sqlite:///"
        if not self.url.startswith(prefix):
            return
        database_path = self.url.removeprefix(prefix)
        if database_path in {":memory:", ""}:
            return
        Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
