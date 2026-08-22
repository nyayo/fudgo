"""Users router: addresses (CRUD) + restaurant-staff management."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.deps import get_session, require_role
from app.auth.passwords import hash_password
from app.core.envelope import success_envelope
from app.core.exceptions import NotFoundError, PermissionError
from app.users.enums import AuthProvider, StaffRole, UserType
from app.users.models import (
    Address,
    RestaurantProfile,
    RestaurantStaffProfile,
    User,
)
from app.users.schemas import (
    AddressCreate,
    AddressResponse,
    AddressUpdate,
    RestaurantStaffCreate,
    RestaurantStaffResponse,
    RestaurantStaffUpdate,
)
from app.users import service as user_service

router = APIRouter()


# ---------------------------------------------------------------------------
# addresses
# ---------------------------------------------------------------------------

@router.get("/users/addresses")
async def list_addresses(
    current: User = Depends(require_role()),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    addrs = await user_service.list_addresses(session, current.id)
    return success_envelope([user_service.serialize_address(a) for a in addrs])


@router.post("/users/addresses")
async def create_address(
    payload: AddressCreate,
    current: User = Depends(require_role()),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    row = await user_service.create_address(
        session, current.id, payload.model_dump()
    )
    await session.commit()
    return success_envelope(user_service.serialize_address(row))


@router.patch("/users/addresses/{address_id}")
async def update_address(
    address_id: uuid.UUID,
    payload: AddressUpdate,
    current: User = Depends(require_role()),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    addr = await user_service.get_own_address(session, current.id, address_id)
    updated = await user_service.update_address(
        session, addr, payload.model_dump(exclude_unset=True)
    )
    await session.commit()
    return success_envelope(user_service.serialize_address(updated))


@router.delete("/users/addresses/{address_id}")
async def delete_address(
    address_id: uuid.UUID,
    current: User = Depends(require_role()),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    addr = await user_service.get_own_address(session, current.id, address_id)
    await session.delete(addr)
    await session.commit()
    return success_envelope({"message": "Address removed"})


# ---------------------------------------------------------------------------
# staff management (restaurant owners)
# ---------------------------------------------------------------------------

async def _caller_restaurant(
    session: AsyncSession, user: User
) -> RestaurantProfile:
    prof = (
        await session.execute(
            select(RestaurantProfile).where(RestaurantProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if prof is None:
        raise PermissionError("Only restaurants can manage staff")
    return prof


def _serialize_staff(
    user: User, profile: RestaurantStaffProfile
) -> dict[str, Any]:
    return {
        "id": str(profile.id),
        "user_id": str(profile.user_id),
        "restaurant_id": str(profile.restaurant_id),
        "role": profile.role.value,
        "is_active": profile.is_active,
        "date_joined": profile.date_joined.isoformat() if profile.date_joined else None,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
    }


@router.get("/users/staff")
async def list_staff(
    current: User = Depends(require_role(UserType.restaurant)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    restaurant = await _caller_restaurant(session, current)
    rows = (
        await session.execute(
            select(RestaurantStaffProfile, User)
            .join(User, User.id == RestaurantStaffProfile.user_id)
            .where(RestaurantStaffProfile.restaurant_id == restaurant.id)
            .order_by(RestaurantStaffProfile.date_joined)
        )
    ).all()
    return success_envelope([_serialize_staff(u, p) for (p, u) in rows])


@router.post("/users/staff")
async def create_staff(
    payload: RestaurantStaffCreate,
    current: User = Depends(require_role(UserType.restaurant)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    restaurant = await _caller_restaurant(session, current)
    existing = (
        await session.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is not None:
        raise NotFoundError(  # 404 keeps the original semantic but 409 is closer
            "An account with that email already exists"
        )
    username = await user_service.generate_unique_username(
        session, UserType.restaurant_staff, payload.email, None
    )
    new_user = User(
        email=payload.email,
        phone=payload.phone,
        username=username,
        first_name=payload.first_name,
        last_name=payload.last_name,
        user_type=UserType.restaurant_staff,
        auth_provider=AuthProvider.email,
        is_verified=True,
        password_hash=hash_password(payload.password),
    )
    session.add(new_user)
    await session.flush()
    profile = RestaurantStaffProfile(
        user_id=new_user.id,
        restaurant_id=restaurant.id,
        role=StaffRole(payload.role),
    )
    session.add(profile)
    await session.flush()
    await session.commit()
    return success_envelope(_serialize_staff(new_user, profile))


@router.patch("/users/staff/{staff_id}")
async def update_staff(
    staff_id: uuid.UUID,
    payload: RestaurantStaffUpdate,
    current: User = Depends(require_role(UserType.restaurant)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    restaurant = await _caller_restaurant(session, current)
    row = (
        await session.execute(
            select(RestaurantStaffProfile, User)
            .join(User, User.id == RestaurantStaffProfile.user_id)
            .where(
                RestaurantStaffProfile.id == staff_id,
                RestaurantStaffProfile.restaurant_id == restaurant.id,
            )
        )
    ).first()
    if row is None:
        raise NotFoundError("Staff member not found")
    profile, user = row
    data = payload.model_dump(exclude_unset=True)
    if "role" in data:
        profile.role = StaffRole(data["role"])
    if "is_active" in data:
        profile.is_active = data["is_active"]
    if "first_name" in data:
        user.first_name = data["first_name"]
    if "last_name" in data:
        user.last_name = data["last_name"]
    await session.flush()
    await session.commit()
    return success_envelope(_serialize_staff(user, profile))


@router.delete("/users/staff/{staff_id}")
async def delete_staff(
    staff_id: uuid.UUID,
    current: User = Depends(require_role(UserType.restaurant)),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    restaurant = await _caller_restaurant(session, current)
    row = (
        await session.execute(
            select(RestaurantStaffProfile).where(
                RestaurantStaffProfile.id == staff_id,
                RestaurantStaffProfile.restaurant_id == restaurant.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Staff member not found")
    await session.delete(row)
    await session.commit()
    return success_envelope({"message": "Staff member removed"})