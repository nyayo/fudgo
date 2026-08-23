"""Image validation + key generation, decoupled from FastAPI's UploadFile.

Order of operations (each step can raise ValidationError before R2 is hit):

1. Read content into memory.
2. Check ``len(content) <= MAX_UPLOAD_SIZE_MB * 1024 * 1024``.
3. Sniff MIME via ``magic.from_buffer(content[:2048], mime=True)``.
4. Validate MIME is in ``ALLOWED_IMAGE_MIME_TYPES``.
5. Open with Pillow to confirm it's a real image and read width/height.
6. Reject if any dimension > ``MAX_IMAGE_DIMENSION_PX``.
7. Derive a safe ``ext`` from the sniffed MIME.
8. Generate the object key.
"""

from __future__ import annotations

import io
import uuid
from typing import Any, Literal

import magic
from PIL import Image

from app.core.config import get_settings
from app.core.exceptions import ValidationError

MIME_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

ImageKind = Literal["menu_item", "menu_category", "promotion"]


def _settings():
    return get_settings()


def validate_image(
    content: bytes, content_type_hint: str | None = None
) -> tuple[str, int, int]:
    """Return (sniffed_mime, width, height) or raise ValidationError."""
    settings = _settings()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise ValidationError(
            f"Image too large: {len(content)} bytes (max {max_bytes})"
        )
    if not content:
        raise ValidationError("Image is empty")

    sniffed = magic.from_buffer(content[:2048], mime=True)
    if sniffed not in settings.ALLOWED_IMAGE_MIME_TYPES:
        raise ValidationError(
            f"Unsupported image type: {sniffed}. "
            f"Allowed: {', '.join(settings.ALLOWED_IMAGE_MIME_TYPES)}"
        )

    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
            img.verify()  # cheap integrity check
    except Exception as exc:  # Pillow raises many types
        raise ValidationError(f"Corrupt or invalid image: {exc}") from exc

    if width > settings.MAX_IMAGE_DIMENSION_PX or height > settings.MAX_IMAGE_DIMENSION_PX:
        raise ValidationError(
            f"Image too large: {width}x{height} "
            f"(max {settings.MAX_IMAGE_DIMENSION_PX}px on any side)"
        )

    del content_type_hint  # we trust the sniffed MIME, not the client header
    return sniffed, width, height


def ext_for_mime(mime: str) -> str:
    if mime not in MIME_TO_EXT:
        raise ValidationError(f"No file extension for {mime}")
    return MIME_TO_EXT[mime]


def generate_object_key(
    restaurant_id: str | uuid.UUID, kind: ImageKind, ext: str
) -> str:
    return f"restaurants/{restaurant_id}/{kind}/{uuid.uuid4()}.{ext}"


async def upload_image_for_restaurant(
    storage: Any,
    restaurant_id: uuid.UUID,
    kind: ImageKind,
    content: bytes,
    content_type_hint: str | None = None,
) -> dict[str, Any]:
    """Validate, upload, return a small DTO ready to persist.

    The DTO contains ``url``, ``content_type``, ``width``, ``height``,
    ``size_bytes``, ``key``.
    """
    mime, width, height = validate_image(content, content_type_hint)
    ext = ext_for_mime(mime)
    key = generate_object_key(restaurant_id, kind, ext)
    url = await storage.upload(content, key, mime)
    return {
        "url": url,
        "key": key,
        "content_type": mime,
        "width": width,
        "height": height,
        "size_bytes": len(content),
    }
