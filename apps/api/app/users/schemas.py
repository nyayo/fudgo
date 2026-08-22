"""Pydantic schemas for the users domain (addresses, staff)."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AddressBase(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    street: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    phone: str = Field(pattern=r"^\+[1-9]\d{1,14}$")
    location: dict[str, Any] = Field(
        description="GeoJSON-shaped point: {'type': 'Point', 'coordinates': [lng, lat]}",
        examples=[{"type": "Point", "coordinates": [36.8, -1.3]}],
    )


class AddressCreate(AddressBase):
    pass


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    street: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")
    location: dict[str, Any] | None = None


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    label: str
    street: str
    city: str
    phone: str
    location: dict[str, Any] | None = None
    created_at: str | None = None


class RestaurantStaffCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)  # type: ignore[assignment]
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(pattern=r"^\+[1-9]\d{1,14}$")
    password: str = Field(min_length=8, max_length=128)
    role: Literal["manager", "waiter", "cashier"]


class RestaurantStaffUpdate(BaseModel):
    role: Literal["manager", "waiter", "cashier"] | None = None
    is_active: bool | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)


class RestaurantStaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID  # staff_profile.id
    user_id: UUID
    restaurant_id: UUID
    role: str
    is_active: bool
    date_joined: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
