"""Image upload + image_service + storage tests.

Always run with FUDGO_NULLPOOL=1.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from app.core.storage import InMemoryStorageService
from app.restaurants.image_service import (
    ext_for_mime,
    generate_object_key,
    upload_image_for_restaurant,
    validate_image,
)
from app.core.exceptions import ValidationError


def _make_png_bytes(width: int = 32, height: int = 32, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(width: int = 32, height: int = 32) -> bytes:
    img = Image.new("RGB", (width, height), "blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_webp_bytes(width: int = 32, height: int = 32) -> bytes:
    img = Image.new("RGB", (width, height), "green")
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


class TestImageValidation:
    def test_validate_png(self) -> None:
        mime, w, h = validate_image(_make_png_bytes())
        assert mime == "image/png"
        assert w == 32 and h == 32

    def test_validate_jpeg(self) -> None:
        mime, w, h = validate_image(_make_jpeg_bytes())
        assert mime == "image/jpeg"

    def test_validate_webp(self) -> None:
        mime, w, h = validate_image(_make_webp_bytes())
        assert mime == "image/webp"

    def test_empty_image_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_image(b"")

    def test_wrong_mime_rejected(self) -> None:
        # Bytes that don't sniff to a known image type.
        with pytest.raises(ValidationError):
            validate_image(b"plain text not an image at all" * 100)

    def test_oversized_image_rejected(self, monkeypatch: Any) -> None:
        from app.core import config

        monkeypatch.setattr(
            config.get_settings(), "MAX_UPLOAD_SIZE_MB", 0
        )
        with pytest.raises(ValidationError):
            validate_image(_make_png_bytes())

    def test_huge_dimensions_rejected(self, monkeypatch: Any) -> None:
        from app.core import config

        monkeypatch.setattr(
            config.get_settings(), "MAX_IMAGE_DIMENSION_PX", 16
        )
        with pytest.raises(ValidationError):
            validate_image(_make_png_bytes(width=64, height=64))

    def test_corrupt_image_rejected(self) -> None:
        # Some bytes that sniff to a known mime but aren't a valid image.
        corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        with pytest.raises(ValidationError):
            validate_image(corrupt)


class TestObjectKey:
    def test_key_layout(self) -> None:
        key = generate_object_key("abc-123", "menu_item", "png")
        assert key.startswith("restaurants/abc-123/menu_item/")
        assert key.endswith(".png")

    def test_ext_for_mime(self) -> None:
        assert ext_for_mime("image/jpeg") == "jpg"
        assert ext_for_mime("image/png") == "png"
        assert ext_for_mime("image/webp") == "webp"
        with pytest.raises(ValidationError):
            ext_for_mime("image/gif")


class TestInMemoryStorage:
    @pytest.mark.asyncio
    async def test_upload_and_delete(self) -> None:
        s = InMemoryStorageService()
        url = await s.upload(b"hello", "test/foo.txt", "text/plain")
        assert url == "https://test.local/test/foo.txt"
        assert await s.exists("test/foo.txt")
        await s.delete("test/foo.txt")
        assert not await s.exists("test/foo.txt")

    @pytest.mark.asyncio
    async def test_round_trip(self) -> None:
        s = InMemoryStorageService()
        content = _make_png_bytes()
        url = await s.upload(content, "restaurants/r/menu_item/x.png", "image/png")
        assert "test.local" in url
        assert s._store["restaurants/r/menu_item/x.png"] == content


class TestUploadImageForRestaurant:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        s = InMemoryStorageService()
        restaurant_id = __import__("uuid").uuid4()
        dto = await upload_image_for_restaurant(
            s, restaurant_id, "menu_item", _make_png_bytes()
        )
        assert dto["content_type"] == "image/png"
        assert dto["url"].startswith("https://test.local/")
        assert dto["size_bytes"] > 0
        assert dto["width"] == 32
        assert dto["height"] == 32


class TestInMemoryStorageDependency:
    def test_in_memory_is_a_storage_service(self) -> None:
        from app.core.storage import StorageService

        assert isinstance(InMemoryStorageService(), StorageService)
