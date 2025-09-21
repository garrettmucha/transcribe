"""Local filesystem storage abstraction for Akash deployments."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Iterable, List

from app.observability.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    """Persist files on the Akash persistent volume."""

    def __init__(self) -> None:
        root = os.getenv("STORAGE_ROOT", "/storage")
        self.root = Path(root).resolve()
        self.uploads_dir = self.root / "uploads"
        self.results_dir = self.root / "results"
        self.public_prefix = os.getenv("STORAGE_PUBLIC_PREFIX", "/storage").rstrip("/")

        for directory in (self.root, self.uploads_dir, self.results_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # Internal helpers -------------------------------------------------

    def _resolve_key(self, key: str) -> Path:
        safe_key = key.lstrip("/")
        path = (self.root / safe_key).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError("Attempt to escape storage root")
        return path

    async def _write_bytes(self, path: Path, data: bytes) -> None:
        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, write)

    async def _read_bytes(self, path: Path) -> bytes:
        def read() -> bytes:
            with open(path, "rb") as handle:
                return handle.read()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, read)

    async def _delete_path(self, path: Path) -> bool:
        def delete() -> bool:
            if path.exists():
                path.unlink()
                return True
            return False

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, delete)

    async def _list_dir(self, prefix: Path) -> List[str]:
        def listdir() -> List[str]:
            if not prefix.exists():
                return []
            return [
                str(path.relative_to(self.root))
                for path in prefix.rglob("*")
                if path.is_file()
            ]

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, listdir)

    # Public API -------------------------------------------------------

    async def upload_file(self, file_content: bytes, key: str, content_type: str | None = None) -> str:
        path = self._resolve_key(key)
        await self._write_bytes(path, file_content)
        logger.debug("Stored file", key=key, bytes=len(file_content))
        return f"file://{path}"

    async def download_file(self, uri: str) -> bytes:
        if not uri.startswith("file://"):
            raise ValueError("Only file:// URIs are supported for local storage")
        path = Path(uri[7:])
        if not path.exists():
            raise FileNotFoundError(str(path))
        return await self._read_bytes(path)

    async def get_signed_url(self, key: str, expires_in: int = 3600) -> str:
        path = self._resolve_key(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return f"{self.public_prefix}/{key}".replace("//", "/")

    async def delete_file(self, uri_or_key: str) -> bool:
        path = (
            Path(uri_or_key[7:])
            if uri_or_key.startswith("file://")
            else self._resolve_key(uri_or_key)
        )
        return await self._delete_path(path)

    async def list_files(self, prefix: str) -> Iterable[str]:
        if prefix.startswith("file://"):
            raise ValueError("list_files expects a storage key prefix")
        base = self._resolve_key(prefix)
        return await self._list_dir(base)

    async def health_check(self) -> dict:
        try:
            probe = self.results_dir / ".probe"
            await self._write_bytes(probe, b"ok")
            await self._delete_path(probe)
            return {"status": "healthy", "root": str(self.root)}
        except Exception as exc:  # pragma: no cover - storage errors vary
            logger.error("Storage health check failed", error=str(exc))
            return {"status": "unhealthy", "error": str(exc)}
