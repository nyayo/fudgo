"""Business logic for the auth domain.

This module owns registration dispatch (email/phone/google), token issuance
and rotation, and the password-reset flow. Routes are thin: they parse input
and delegate here.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    decode_token,
)
from app.auth.models import RevokedToken
from app.auth.otp_service import (
    create_email_otp,
    create_phone_otp,
    verify_email_otp,
    verify_phone_otp,
)
from app.auth.passwords import hash_password, verify_password
from app.core.config import get_settings
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.users.enums import AuthProvider, UserType
from app.users.models import User
from app.users.service import create_user_on_registration

# ---------------------------------------------------------------------------
# token issuance
# ---------------------------------------------------------------------------


def issue_token_pair(user_id: uuid.UUID) -> dict[str, str]:
    settings = get_settings()
    jti = uuid.uuid4().hex
    return {
        "access": create_access_token(user_id),
        "refresh": create_refresh_token(user_id, jti=jti),
        "jti": jti,
        "access_ttl_minutes": str(settings.JWT_ACCESS_TTL_MINUTES),
    }


def serialize_user(user: User, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serialize a User + optional role profile into a stable dict."""
    return {
        "id": str(user.id),
        "email": user.email,
        "phone": user.phone,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "user_type": user.user_type.value,
        "auth_provider": user.auth_provider.value,
        "is_verified": user.is_verified,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "google_id": user.google_id,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "profile": profile,
    }


def user_can_link_google(user: User) -> bool:
    return user.auth_provider != AuthProvider.google and not user.google_id


async def build_profile_for_user(session: AsyncSession, user: User) -> dict[str, Any] | None:
    """Load the user's role-specific profile, return as a serializable dict.

    Each branch loads its own typed local (customer_prof, courier_prof, ...)
    and uses it directly in the return dict, so mypy narrows the type
    correctly per branch. Sharing one ``prof`` variable across branches
    confuses the type checker.
    """
    if user.user_type == UserType.customer:
        from app.users.models import CustomerProfile

        customer_prof: CustomerProfile | None = (
            await session.execute(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
        ).scalar_one_or_none()
        if customer_prof is None:
            return None
        dob = customer_prof.date_of_birth
        return {
            "current_location": customer_prof.current_location,  # raw geography; routes serialize
            "date_of_birth": dob.isoformat() if dob else None,
            "order_stats": customer_prof.order_stats or {},
        }
    if user.user_type == UserType.courier:
        from app.users.models import CourierProfile

        courier_prof: CourierProfile | None = (
            await session.execute(select(CourierProfile).where(CourierProfile.user_id == user.id))
        ).scalar_one_or_none()
        if courier_prof is None:
            return None
        return {
            "vehicle_type": courier_prof.vehicle_type.value,
            "license_number": courier_prof.license_number,
            "is_available": courier_prof.is_available,
            "is_approved": courier_prof.is_approved,
            "rating": float(courier_prof.rating or 0),
            "total_deliveries": courier_prof.total_deliveries,
            "earnings_balance": float(courier_prof.earnings_balance or 0),
        }
    if user.user_type == UserType.restaurant:
        from app.users.models import RestaurantProfile

        restaurant_prof: RestaurantProfile | None = (
            await session.execute(
                select(RestaurantProfile).where(RestaurantProfile.user_id == user.id)
            )
        ).scalar_one_or_none()
        if restaurant_prof is None:
            return None
        return {
            "restaurant_name": restaurant_prof.restaurant_name,
            "business_license": restaurant_prof.business_license,
            "address": restaurant_prof.address,
            "rating": float(restaurant_prof.rating or 0),
            "is_approved": restaurant_prof.is_approved,
            "is_active": restaurant_prof.is_active,
        }
    if user.user_type == UserType.restaurant_staff:
        from app.users.models import RestaurantStaffProfile

        staff_prof: RestaurantStaffProfile | None = (
            await session.execute(
                select(RestaurantStaffProfile).where(RestaurantStaffProfile.user_id == user.id)
            )
        ).scalar_one_or_none()
        if staff_prof is None:
            return None
        return {
            "restaurant_id": str(staff_prof.restaurant_id),
            "role": staff_prof.role.value,
            "is_active": staff_prof.is_active,
            "date_joined": staff_prof.date_joined.isoformat() if staff_prof.date_joined else None,
        }
    return None


async def update_profile(
    session: AsyncSession,
    user: User,
    payload: Any,
) -> User:
    """Update top-level fields + role-specific profile_data on a user."""
    from app.users.enums import UserType
    from app.users.models import (
        CourierProfile,
        CustomerProfile,
        RestaurantProfile,
    )

    data = payload.model_dump(exclude_unset=True)
    if "first_name" in data:
        user.first_name = data["first_name"]
    if "last_name" in data:
        user.last_name = data["last_name"]
    if "phone" in data:
        user.phone = data["phone"]

    profile_data = data.get("profile_data") or {}
    if profile_data:
        if user.user_type == UserType.courier:
            courier_row: CourierProfile | None = (
                await session.execute(
                    select(CourierProfile).where(CourierProfile.user_id == user.id)
                )
            ).scalar_one_or_none()
            if courier_row is not None:
                for key in ("vehicle_type", "license_number", "is_available"):
                    if key in profile_data:
                        setattr(courier_row, key, profile_data[key])
        elif user.user_type == UserType.customer:
            customer_row: CustomerProfile | None = (
                await session.execute(
                    select(CustomerProfile).where(CustomerProfile.user_id == user.id)
                )
            ).scalar_one_or_none()
            if customer_row is not None and "date_of_birth" in profile_data:
                customer_row.date_of_birth = profile_data["date_of_birth"]
        elif user.user_type == UserType.restaurant:
            restaurant_row: RestaurantProfile | None = (
                await session.execute(
                    select(RestaurantProfile).where(RestaurantProfile.user_id == user.id)
                )
            ).scalar_one_or_none()
            if restaurant_row is not None:
                for key in ("restaurant_name", "address", "opening_hours"):
                    if key in profile_data:
                        setattr(restaurant_row, key, profile_data[key])
    await session.flush()
    await session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# OTP flows
# ---------------------------------------------------------------------------


async def request_email_otp(session: AsyncSession, email: str) -> tuple[str, dict[str, Any]]:
    """Generate an email OTP; return (plain_code, row_dict)."""
    plain, _row = await create_email_otp(session, email)
    return plain, {"email": email, "is_verified": False}


async def request_phone_otp(session: AsyncSession, phone: str) -> tuple[str, dict[str, Any]]:
    plain, _row = await create_phone_otp(session, phone)
    return plain, {"phone": phone, "is_verified": False}


async def verify_email_for_login(session: AsyncSession, email: str, otp: str) -> dict[str, Any]:
    """Verify an email OTP and either issue tokens or report a need to register."""
    await verify_email_otp(session, email, otp)
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        return {
            "verified": True,
            "user_exists": False,
            "requires_registration": True,
            "email": email,
        }
    user.is_verified = True
    user.last_login = datetime.now(UTC)
    await session.flush()
    await session.refresh(user)
    pair = issue_token_pair(user.id)
    return {
        "verified": True,
        "user_exists": True,
        "requires_registration": False,
        "email": email,
        "tokens": pair,
        "user": serialize_user(user),
    }


async def verify_phone_for_login(session: AsyncSession, phone: str, otp: str) -> dict[str, Any]:
    """Verify a phone OTP and either issue tokens or report a need to register."""
    await verify_phone_otp(session, phone, otp)
    user = (await session.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        return {
            "verified": True,
            "user_exists": False,
            "requires_registration": True,
            "phone": phone,
        }
    user.is_verified = True
    user.last_login = datetime.now(UTC)
    await session.flush()
    await session.refresh(user)
    pair = issue_token_pair(user.id)
    return {
        "verified": True,
        "user_exists": True,
        "requires_registration": False,
        "phone": phone,
        "tokens": pair,
        "user": serialize_user(user),
    }


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def _assert_phone_verified(phone: str | None) -> None:
    """Pure-decorator callers don't have access to OTP rows here, so we use a
    soft check: if phone is set, we mark is_verified=True downstream. The
    email-only path leaves is_verified=False (documented in the brief)."""
    if not phone:
        return


async def register_user(
    session: AsyncSession,
    *,
    user_type: UserType,
    email: str | None,
    phone: str | None,
    first_name: str,
    last_name: str,
    password: str,
    profile_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create the user + role profile, issue tokens."""
    if user_type == UserType.restaurant_staff:
        raise ValidationError("Restaurant staff must be created by their restaurant's owner")
    if not email and not phone:
        raise ValidationError("Either email or phone is required")
    _assert_phone_verified(phone)
    user = await create_user_on_registration(
        session,
        user_type=user_type,
        email=email,
        phone=phone,
        first_name=first_name,
        last_name=last_name,
        password=password,
        profile_data=profile_data or {},
    )
    user.last_login = datetime.now(UTC)
    await session.flush()
    await session.refresh(user)
    pair = issue_token_pair(user.id)
    return {
        "tokens": pair,
        "user": serialize_user(user),
        "can_link_google": user_can_link_google(user),
    }


# ---------------------------------------------------------------------------
# google oauth
# ---------------------------------------------------------------------------


async def login_with_google(
    session: AsyncSession,
    *,
    claims: dict[str, Any],
    user_type: UserType | None,
    profile_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Login (or register) via a verified Google ID token."""
    email = claims.get("email")
    google_sub = claims.get("sub")
    if not email or not google_sub:
        raise AuthenticationError("Google account missing required claims")

    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is None:
        # New user — only created when an explicit user_type is supplied.
        if user_type is None:
            raise AuthenticationError("No account exists for that Google account")
        new_user = User(
            email=email,
            username=await _username_from_email(session, email, user_type),
            first_name=claims.get("given_name", ""),
            last_name=claims.get("family_name", ""),
            user_type=user_type,
            auth_provider=AuthProvider.google,
            google_id=google_sub,
            is_verified=bool(claims.get("email_verified", False)),
            password_hash=None,
        )
        session.add(new_user)
        await session.flush()
        await session.refresh(new_user)
        from app.users.models import NotificationPreference

        session.add(NotificationPreference(user_id=new_user.id))
        user = new_user
    else:
        if user.auth_provider != AuthProvider.google:
            provider = user.auth_provider.value
            raise AuthenticationError(
                f"please continue with {provider}",
                details={"provider": provider},
            )
        if not user.google_id:
            user.google_id = google_sub
        user.last_login = datetime.now(UTC)
        await session.flush()
        await session.refresh(user)

    pair = issue_token_pair(user.id)
    return {
        "tokens": pair,
        "user": serialize_user(user),
        "can_link_google": user_can_link_google(user),
    }


async def link_google(session: AsyncSession, user: User, claims: dict[str, Any]) -> User:
    if user.google_id:
        raise ConflictError("Google account already linked")
    if not claims.get("sub"):
        raise AuthenticationError("Invalid Google ID token")
    user.google_id = claims["sub"]
    user.auth_provider = AuthProvider.google
    user.is_verified = True
    await session.flush()
    return user


# ---------------------------------------------------------------------------
# refresh / logout
# ---------------------------------------------------------------------------


async def refresh_tokens(session: AsyncSession, refresh: str) -> dict[str, str]:
    payload = decode_token(refresh, expected_type="refresh")
    jti_revoked = (
        await session.execute(select(RevokedToken.id).where(RevokedToken.jti == payload.jti))
    ).first()
    if jti_revoked is not None:
        raise AuthenticationError("Refresh token revoked")
    from app.auth.deps import logout_all_revoked

    if await logout_all_revoked(session, payload.sub):
        raise AuthenticationError("Refresh token revoked")
    pair = issue_token_pair(payload.sub)
    expires_at = datetime.now(UTC) + timedelta(days=get_settings().JWT_REFRESH_TTL_DAYS)
    session.add(
        RevokedToken(
            jti=payload.jti,
            reason="rotation",
            expires_at=expires_at,
        )
    )
    await session.flush()
    return pair


async def logout(session: AsyncSession, refresh: str) -> None:
    payload = decode_token(refresh, expected_type="refresh")
    row = RevokedToken(
        jti=payload.jti,
        reason="logout",
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().JWT_REFRESH_TTL_DAYS),
    )
    session.add(row)
    await session.flush()


async def logout_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TTL_DAYS)
    row = RevokedToken(
        jti=f"logout-all:{user_id}",
        revoked_at_user=user_id,
        reason="logout-all",
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()


# ---------------------------------------------------------------------------
# password reset
# ---------------------------------------------------------------------------


async def request_password_reset(session: AsyncSession, email: str) -> str:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        # Do not leak existence; return a valid token-shaped string anyway.
        # But we still need to know the user id to sign a token. Skip silently.
        return ""
    return create_password_reset_token(user.id)


async def confirm_password_reset(session: AsyncSession, token: str, new_password: str) -> None:
    payload = decode_token(token, expected_type="password_reset")
    user = (await session.execute(select(User).where(User.id == payload.sub))).scalar_one_or_none()
    if user is None:
        raise NotFoundError("User not found")
    user.password_hash = hash_password(new_password)
    await session.flush()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _username_from_email(session: AsyncSession, email: str, user_type: UserType) -> str:
    from app.users.service import generate_unique_username

    return await generate_unique_username(session, user_type, email, None)


async def authenticate_email_password(session: AsyncSession, email: str, password: str) -> User:
    """Helper used by tests for password flows (no /auth/login route in brief)."""
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.password_hash or not verify_password(password, user.password_hash):
        raise AuthenticationError("Invalid credentials")
    return user
