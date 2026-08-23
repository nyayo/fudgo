"""Pydantic schemas for the restaurants domain.

Mirror v1 field names exactly. Responses have ``from_attributes=True`` so
SQLModel rows can be returned directly via ``model_validate``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings


# ---------------------------------------------------------------------------
# Restaurant (RestaurantProfile re-exposed)
# ---------------------------------------------------------------------------


class RestaurantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    restaurant_name: str
    business_license: str
    address: str
    latitude: float
    longitude: float
    opening_hours: dict[str, Any] = Field(default_factory=dict)
    rating: float
    is_approved: bool
    is_active: bool
    image_url: str | None = None
    logo_url: str | None = None


class RestaurantUpdate(BaseModel):
    restaurant_name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=2000)
    opening_hours: dict[str, Any] | None = None
    image_url: str | None = None
    logo_url: str | None = None


class RestaurantListResponse(BaseModel):
    id: UUID
    restaurant_name: str
    address: str
    rating: float
    image_url: str | None = None
    distance_km: float | None = None
    latitude: float
    longitude: float


class NearbyQuery(BaseModel):
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    radius_km: float = 5.0

    @field_validator("radius_km")
    @classmethod
    def _check_radius(cls, v: float) -> float:
        max_radius = get_settings().MAX_SEARCH_RADIUS_KM
        if v <= 0:
            raise ValueError("radius_km must be > 0")
        if v > max_radius:
            raise ValueError(f"radius_km must be <= {max_radius}")
        return v


class PaginatedRestaurants(BaseModel):
    items: list[RestaurantListResponse]
    count: int
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


class PromotionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=225)
    discount: float = Field(ge=0.0, le=100.0)
    start_date: datetime
    end_date: datetime
    is_active: bool = True

    @field_validator("end_date")
    @classmethod
    def _dates(cls, v: datetime, info: Any) -> datetime:
        start = info.data.get("start_date")
        if start is not None and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class PromotionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=225)
    discount: float | None = Field(default=None, ge=0.0, le=100.0)
    start_date: datetime | None = None
    end_date: datetime | None = None
    is_active: bool | None = None


class PromotionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    restaurant_name: str | None = None
    name: str
    description: str
    banner_url: str | None
    discount: float
    start_date: datetime
    end_date: datetime
    is_active: bool
    is_currently_active: bool
    created_at: datetime


# ---------------------------------------------------------------------------
# MenuCategory
# ---------------------------------------------------------------------------


class MenuCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    position: int = 0
    is_active: bool = True


class MenuCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    position: int | None = None
    is_active: bool | None = None


class MenuCategoryImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_url: str
    alt_text: str
    created_at: datetime


class MenuCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    name: str
    description: str
    position: int
    is_active: bool
    image_url: str | None = None
    items_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# MenuItem
# ---------------------------------------------------------------------------


class MenuItemImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    image_url: str
    alt_text: str
    position: int


class MenuItemCreate(BaseModel):
    restaurant_id: UUID
    category_id: UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    price: Decimal = Field(ge=Decimal("0.01"), max_digits=10, decimal_places=2)
    is_available: bool = True
    is_featured: bool = False
    prep_time_minutes: int | None = Field(default=None, ge=0)
    allergens: str = ""
    promotion_ids: list[UUID] = Field(default_factory=list)


class MenuItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=Decimal("0.01"), max_digits=10, decimal_places=2)
    is_available: bool | None = None
    is_featured: bool | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)
    allergens: str | None = None
    category_id: UUID | None = None
    promotion_ids: list[UUID] | None = None


class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    restaurant_id: UUID
    restaurant_name: str | None = None
    category_id: UUID
    category_name: str | None = None
    title: str
    description: str
    price: Decimal
    discounted_price: Decimal | None = None
    applied_promotion: PromotionResponse | None = None
    is_available: bool
    is_featured: bool
    prep_time_minutes: int | None
    allergens: str
    promotions: list[PromotionResponse] = Field(default_factory=list)
    images: list[MenuItemImageResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MenuItemListResponse(BaseModel):
    items: list[MenuItemResponse]
    count: int
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------------
# Misc DTOs
# ---------------------------------------------------------------------------


class PromotionAttachBody(BaseModel):
    promotion_id: UUID


class MessageDTO(BaseModel):
    message: str
