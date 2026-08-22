"""Business logic for the users domain.

This module owns profile construction/serialization, username auto-generation,
register-time profile creation, and the CRUD for addresses and restaurant staff.
All functions are async and raise :class:`AppError` subclasses on failure.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.users.enums import AuthProvider, StaffRole, UserType, VehicleType
from app.users.models import (
    Address,
    CourierProfile,
    CustomerProfile,
    NotificationPreference,
    RestaurantProfile,
    RestaurantStaffProfile,
    User,
)


def now_utc() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# serialization helpers
# ---------------------------------------------------------------------------

def _point_to_coords(value: Any) -> list[float] | None:
    """Convert a stored geography to [lng, lat]; None if null/empty."""
    if value is None:
        return None
    try:
        g = to_shape(value)
        return [float(g.x), float(g.y)]
    except Exception:
        return None


def build_profile_dict(user: User) -> dict[str, Any] | None:
    """Return the user's role-specific profile fields as a plain dict."""
    if user.user_type == UserType.customer:
        return {"current_location": None, "date_of_birth": None, "order_stats": {}}
    if user.user_type == UserType.courier:
        return {"vehicle_type": None, "is_available": True, "rating": 0.0}
    if user.user_type == UserType.restaurant:
        return {"restaurant_name": "", "rating": 0.0, "is_approved": False}
    if user.user_type == UserType.restaurant_staff:
        return {"role": None}
    return None


# ---------------------------------------------------------------------------
# username generation
# ---------------------------------------------------------------------------

def _base_username(user_type: UserType, email: str | None, phone: str | None) -> str:
    key = email.split("@")[0] if email else (phone or "user")
    key = "".join(ch for ch in key if ch.isalnum()).lower() or "user"
    prefixes = {
        UserType.customer: "customer",
        UserType.courier: "courier",
        UserType.restaurant: "restaurant",
        UserType.restaurant_staff: "staff",
    }
    return f"{prefixes[user_type]}_{key}"


async def generate_unique_username(
    session: AsyncSession, user_type: UserType, email: str | None, phone: str | None
) -> str:
    """Auto-generate a unique username, appending a short suffix on collision."""
    base = _base_username(user_type, email, phone)
    candidate = base
    for _ in range(10):
        exists = (
            await session.execute(select(User.id).where(User.username == candidate))
        ).first()
        if exists is None:
            return candidate
        candidate = f"{base}_{uuid.uuid4().hex[:6]}"
    raise ConflictError("Could not allocate a unique username")


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

async def create_user_on_registration(
    session: AsyncSession,
    *,
    user_type: UserType,
    email: str | None,
    phone: str | None,
    first_name: str,
    last_name: str,
    password: str,
    profile_data: dict[str, Any],
) -> User:
    """Create a User plus its role profile and a default NotificationPreference."""
    if email:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("An account with that email already exists")
    if phone:
        existing_phone = (
            await session.execute(select(User).where(User.phone == phone))
        ).scalar_one_or_none()
        if existing_phone is not None:
            raise ConflictError("An account with that phone already exists")

    username = await generate_unique_username(session, user_type, email, phone)
    user = User(
        email=email,
        phone=phone,
        username=username,
        first_name=first_name,
        last_name=last_name,
        user_type=user_type,
        auth_provider=AuthProvider.phone if phone else AuthProvider.email,
        is_verified=bool(phone),  # phone path implies OTP verified
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.flush()

    # Create the role profile matching user_type.
    if user_type == UserType.customer:
        session.add(CustomerProfile(user_id=user.id, order_stats={}))
    elif user_type == UserType.courier:
        vehicle = profile_data.get("vehicle_type", "bike")
        try:
            vehicle_enum = VehicleType(vehicle)
        except ValueError:
            vehicle_enum = VehicleType.bike
        session.add(
            CourierProfile(
                user_id=user.id,
                vehicle_type=vehicle_enum,
                license_number=profile_data.get("license_number"),
                performance_stats={},
            )
        )
    elif user_type == UserType.restaurant:
        loc = profile_data.get("location") or [0.0, 0.0]
        session.add(
            RestaurantProfile(
                user_id=user.id,
                restaurant_name=profile_data.get("restaurant_name") or "My Restaurant",
                business_license=profile_data.get("business_license") or f"LIC-{uuid.uuid4().hex[:10]}",
                address=profile_data.get("address") or "",
                location=from_shape(Point(loc[0], loc[1]), srid=4326),
                opening_hours={},
            )
        )
    elif user_type == UserType.restaurant_staff:
        session.add(
            RestaurantStaffProfile(
                user_id=user.id,
                restaurant_id=profile_data.get("restaurant_id"),
                role=StaffRole(profile_data.get("role", "waiter")),
            )
        )

    session.add(NotificationPreference(user_id=user.id))
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# notification preferences
# ---------------------------------------------------------------------------

async def get_notifications(session: AsyncSession, user_id: uuid.UUID) -> NotificationPreference:
    pref = (
        await session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user_id)
        session.add(pref)
        await session.flush()
    return pref


# ---------------------------------------------------------------------------
# addresses
# ---------------------------------------------------------------------------

async def list_addresses(session: AsyncSession, user_id: uuid.UUID) -> list[Address]:
    rows = (
        await session.execute(
            select(Address).where(Address.user_id == user_id).order_by(Address.created_at)
        )
    ).scalars().all()
    return list(rows)


def _coords_from_location(loc: dict[str, Any]) -> list[float]:
    """Accept either {lng, lat} or GeoJSON {type: 'Point', coordinates: [lng, lat]}."""
    if "coordinates" in loc and isinstance(loc["coordinates"], (list, tuple)):
        return [float(loc["coordinates"][0]), float(loc["coordinates"][1])]
    if "lng" in loc and "lat" in loc:
        return [float(loc["lng"]), float(loc["lat"])]
    if "x" in loc and "y" in loc:
        return [float(loc["x"]), float(loc["y"])]
    raise ValidationError("Invalid location payload")


async def create_address(
    session: AsyncSession,
    user_id: uuid.UUID,
    data: dict[str, Any],
) -> Address:
    coords = _coords_from_location(data.pop("location"))
    row = Address(
        user_id=user_id,
        label=data["label"],
        street=data["street"],
        city=data["city"],
        phone=data["phone"],
        location=from_shape(Point(coords[0], coords[1]), srid=4326),
    )
    session.add(row)
    await session.flush()
    return row


async def get_own_address(session: AsyncSession, user_id: uuid.UUID, address_id: uuid.UUID) -> Address:
    row = (
        await session.execute(
            select(Address).where(Address.id == address_id, Address.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Address not found")
    return row


async def update_address(session: AsyncSession, addr: Address, data: dict[str, Any]) -> Address:
    if "location" in data:
        coords = _coords_from_location(data.pop("location"))
        addr.location = from_shape(Point(coords[0], coords[1]), srid=4326)
    for key, value in data.items():
        if hasattr(addr, key):
            setattr(addr, key, value)
    await session.flush()
    return addr


def serialize_address(addr: Address) -> dict[str, Any]:
    return {
        "id": str(addr.id),
        "user_id": str(addr.user_id),
        "label": addr.label,
        "street": addr.street,
        "city": addr.city,
        "phone": addr.phone,
        "location": _point_to_coords(addr.location),
        "created_at": addr.created_at.isoformat() if addr.created_at else None,
    }