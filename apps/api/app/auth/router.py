"""Auth router: OTP, JWT lifecycle, Google sign-in, password reset, profile, prefs, devices."""

import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service as auth_service
from app.auth.deps import get_current_user, get_session, limiter
from app.auth.google import verify_google_id_token
from app.auth.schemas import (
    DeviceRegisterSchema,
    GoogleSignInSchema,
    LinkGoogleAccountSchema,
    LogoutSchema,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    PasswordResetRequestSchema,
    RegisterSchema,
    RequestOTPSchema,
    RequestPhoneOTPSchema,
    SetNewPasswordSchema,
    TokenRefreshSchema,
    TokenResponse,
    UserProfileUpdate,
    VerifyOTPSchema,
    VerifyPhoneOTPSchema,
)
from app.auth.services import email as email_service
from app.auth.services import push as push_service
from app.auth.services import sms as sms_service
from app.core.envelope import success_envelope
from app.users.enums import UserType
from app.users.models import Device, User
from app.users.service import get_notifications

router = APIRouter()


def _client_ip(request: Request) -> str:
    """slowapi extracts this via key_func; we re-use its helper."""
    from slowapi.util import get_remote_address

    return get_remote_address(request) or "anonymous"


# ---------------------------------------------------------------------------
# OTP / sign-in
# ---------------------------------------------------------------------------


@router.post("/auth/request-otp")
@limiter.limit("5/minute")
async def request_otp(
    request: Request,  # required by slowapi
    payload: RequestOTPSchema,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    plain, _row = await auth_service.request_email_otp(session, payload.email)
    await session.flush()
    await session.commit()
    background.add_task(email_service.send_otp, payload.email, plain)
    return success_envelope({"message": "OTP sent successfully to your email"})


@router.post("/auth/verify-otp")
@limiter.limit("5/minute")
async def verify_otp(
    request: Request,  # noqa: ARG001
    payload: VerifyOTPSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await auth_service.verify_email_for_login(session, payload.email, payload.otp)
    await session.commit()
    return success_envelope(result)


@router.post("/auth/phone/request-otp")
@limiter.limit("5/minute")
async def request_phone_otp(
    request: Request,  # noqa: ARG001
    payload: RequestPhoneOTPSchema,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    plain, _row = await auth_service.request_phone_otp(session, payload.phone)
    await session.flush()
    await session.commit()
    background.add_task(sms_service.send_otp, payload.phone, plain)
    return success_envelope({"message": "OTP sent successfully to your phone"})


@router.post("/auth/phone/verify-otp")
@limiter.limit("5/minute")
async def verify_phone_otp(
    request: Request,  # noqa: ARG001
    payload: VerifyPhoneOTPSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await auth_service.verify_phone_for_login(session, payload.phone, payload.otp)
    await session.commit()
    return success_envelope(result)


@router.post("/auth/register")
async def register(
    payload: RegisterSchema, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    result = await auth_service.register_user(
        session,
        user_type=UserType(payload.user_type),
        email=payload.email,
        phone=payload.phone,
        first_name=payload.first_name,
        last_name=payload.last_name,
        password=payload.password,
        profile_data=payload.profile_data,
    )
    await session.commit()
    return success_envelope(
        {
            "access": result["tokens"]["access"],
            "refresh": result["tokens"]["refresh"],
            "user": result["user"],
            "can_link_google": result["can_link_google"],
        }
    )


@router.post("/auth/google")
@limiter.limit("10/minute")
async def google_signin(
    request: Request,  # noqa: ARG001
    payload: GoogleSignInSchema,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    claims = verify_google_id_token(payload.id_token)
    user_type = UserType(payload.user_type) if payload.user_type else None
    result = await auth_service.login_with_google(
        session,
        claims=claims,
        user_type=user_type,
        profile_data=payload.profile_data,
    )
    await session.commit()
    return success_envelope(
        {
            "access": result["tokens"]["access"],
            "refresh": result["tokens"]["refresh"],
            "user": result["user"],
            "can_link_google": result["can_link_google"],
        }
    )


@router.post("/auth/link-google")
async def link_google(
    payload: LinkGoogleAccountSchema,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    claims = verify_google_id_token(payload.id_token)
    await auth_service.link_google(session, current, claims)
    await session.commit()
    return success_envelope({"message": "Google account linked"})


# ---------------------------------------------------------------------------
# JWT lifecycle
# ---------------------------------------------------------------------------


@router.post("/auth/logout")
async def logout(
    payload: LogoutSchema,
    current: User = Depends(get_current_user),  # noqa: ARG001
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await auth_service.logout(session, payload.refresh)
    await session.commit()
    return success_envelope({"message": "Logged out"})


@router.post("/auth/logout-all")
async def logout_all(
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await auth_service.logout_all(session, current.id)
    await session.commit()
    return success_envelope({"message": "All sessions revoked"})


@router.post("/auth/refresh")
async def refresh(
    payload: TokenRefreshSchema, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    pair = await auth_service.refresh_tokens(session, payload.refresh)
    await session.commit()
    return success_envelope(
        TokenResponse(access=pair["access"], refresh=pair["refresh"]).model_dump()
    )


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@router.get("/auth/profile")
async def get_profile(
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    profile = await auth_service.build_profile_for_user(session, current)
    return success_envelope(auth_service.serialize_user(current, profile=profile))


@router.patch("/auth/profile")
async def update_profile(
    payload: UserProfileUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    updated = await auth_service.update_profile(session, current, payload)
    await session.commit()
    profile = await auth_service.build_profile_for_user(session, updated)
    return success_envelope(auth_service.serialize_user(updated, profile=profile))


# ---------------------------------------------------------------------------
# password reset
# ---------------------------------------------------------------------------


@router.post("/auth/password-reset")
@limiter.limit("3/hour")
async def request_password_reset(
    request: Request,  # noqa: ARG001
    payload: PasswordResetRequestSchema,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    token = await auth_service.request_password_reset(session, payload.email)
    await session.commit()
    if token:
        background.add_task(email_service.send_password_reset, payload.email, token)
    return success_envelope({"message": "If the account exists, an email was sent"})


@router.post("/auth/password-reset/confirm")
async def confirm_password_reset(
    payload: SetNewPasswordSchema, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    await auth_service.confirm_password_reset(session, payload.token, payload.password)
    await session.commit()
    return success_envelope({"message": "Password updated"})


# ---------------------------------------------------------------------------
# notification preferences
# ---------------------------------------------------------------------------


@router.get("/auth/notification-preferences")
async def get_notification_prefs(
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    pref = await get_notifications(session, current.id)
    await session.commit()
    return success_envelope(NotificationPreferenceResponse.model_validate(pref).model_dump())


@router.patch("/auth/notification-preferences")
async def patch_notification_prefs(
    payload: NotificationPreferenceUpdate,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    pref = await get_notifications(session, current.id)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(pref, key, value)
    await session.flush()
    await session.commit()
    return success_envelope(NotificationPreferenceResponse.model_validate(pref).model_dump())


# ---------------------------------------------------------------------------
# devices
# ---------------------------------------------------------------------------


@router.post("/auth/devices")
async def register_device(
    payload: DeviceRegisterSchema,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from app.users.enums import DevicePlatform

    device = Device(
        user_id=current.id,
        registration_id=payload.registration_id,
        platform=DevicePlatform(payload.platform),
    )
    session.add(device)
    await session.flush()
    await push_service.register(current.id, payload.registration_id, payload.platform)
    await session.commit()
    return success_envelope({"message": "Device registered", "device_id": str(device.id)})


@router.delete("/auth/devices/{device_id}")
async def delete_device(
    device_id: uuid.UUID,
    current: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    from sqlalchemy import delete, select

    device = (
        await session.execute(
            select(Device).where(Device.id == device_id, Device.user_id == current.id)
        )
    ).scalar_one_or_none()
    if device is None:
        return success_envelope({"message": "Device not found"})

    await session.execute(
        delete(Device).where(Device.id == device_id, Device.user_id == current.id)
    )
    await session.flush()
    await session.commit()
    return success_envelope({"message": "Device removed"})


@router.post("/auth/test-notification")
async def test_notification(
    current: User = Depends(get_current_user),
) -> dict[str, Any]:
    await push_service.send(current.id, "Test", "Hello from Fudgo!")
    return success_envelope({"message": "Test notification dispatched (stub)"})
