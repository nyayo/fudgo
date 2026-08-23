"""Storage service abstraction + R2 (Cloudflare S3-compatible) implementation.

Tests swap the dependency for :class:`InMemoryStorageService`. The R2
implementation keeps a single aioboto3 session for the app's lifetime and
opens a client per call (cheap; aioboto3 sessions are reusable).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import aioboto3
import structlog

from app.core.config import get_settings

logger = structlog.get_logger("fudgo.storage")


class StorageService(ABC):
    @abstractmethod
    async def upload(self, content: bytes, key: str, content_type: str) -> str:
        """Persist ``content`` at ``key``; return the public URL."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object at ``key`` if present."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True iff the object at ``key`` is present."""


def _endpoint_url() -> str:
    settings = get_settings()
    if settings.R2_ENDPOINT_URL:
        return settings.R2_ENDPOINT_URL
    return f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def _public_url(key: str) -> str:
    settings = get_settings()
    if settings.R2_CUSTOM_DOMAIN:
        return f"https://{settings.R2_CUSTOM_DOMAIN}/{key}"
    return f"{_endpoint_url()}/{settings.R2_BUCKET_NAME}/{key}"


class R2StorageService(StorageService):
    """Real R2 (S3-compatible) implementation via aioboto3."""

    def __init__(self) -> None:
        self._session = aioboto3.Session()

    async def upload(self, content: bytes, key: str, content_type: str) -> str:
        settings = get_settings()
        async with self._session.client(
            "s3",
            endpoint_url=_endpoint_url(),
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name=settings.R2_REGION,
        ) as s3:
            await s3.put_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=key,
                Body=content,
                ContentType=content_type,
                ACL="public-read",
            )
        return _public_url(key)

    async def delete(self, key: str) -> None:
        settings = get_settings()
        async with self._session.client(
            "s3",
            endpoint_url=_endpoint_url(),
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name=settings.R2_REGION,
        ) as s3:
            await s3.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)

    async def exists(self, key: str) -> bool:
        settings = get_settings()
        async with self._session.client(
            "s3",
            endpoint_url=_endpoint_url(),
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name=settings.R2_REGION,
        ) as s3:
            try:
                await s3.head_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
                return True
            except Exception:  # noqa: BLE001
                return False


class InMemoryStorageService(StorageService):
    """In-memory storage used by tests. Returns ``https://test.local/{key}`` URLs."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.uploads: list[tuple[str, int, str]] = []  # key, size, content_type
        self.deletes: list[str] = []

    async def upload(self, content: bytes, key: str, content_type: str) -> str:
        self._store[key] = content
        self.uploads.append((key, len(content), content_type))
        return f"https://test.local/{key}"

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self.deletes.append(key)

    async def exists(self, key: str) -> bool:
        return key in self._store


# Module-level singleton + FastAPI dependency. main.py attaches the
# :class:`R2StorageService` instance to ``app.state.storage`` at startup;
# the dependency returns it on each request.
_storage: StorageService | None = None


def set_storage_service(service: StorageService) -> None:
    global _storage
    _storage = service


def get_storage_service() -> StorageService:
    if _storage is None:
        # Lazy fallback so the dependency is importable even if the
        # lifespan hasn't initialised storage yet (e.g. in tests that
        # forget the override).
        set_storage_service(InMemoryStorageService())
    assert _storage is not None  # set by the line above
    return _storage
