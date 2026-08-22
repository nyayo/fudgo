"""Pydantic schemas for the auth domain."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RequestOTPSchema(BaseModel):
    email: EmailStr


class VerifyOTPSchema(BaseModel):
    email: EmailStr
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RequestPhoneOTPSchema(BaseModel):
    phone: str = Field(pattern=r"^\+[1-9]\d{1,14}$", description="E.164 phone number")


class VerifyPhoneOTPSchema(BaseModel):
    phone: str = Field(pattern=r"^\+[1-9]\d{1,14}$")
    otp: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RegisterSchema(BaseModel):
    user_type: Literal["customer", "courier", "restaurant", "restaurant_staff"]
    email: EmailStr | None = None
    phone: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    profile_data: dict[str, Any] = Field(default_factory=dict)


class GoogleSignInSchema(BaseModel):
    id_token: str
    user_type: Literal["customer", "courier", "restaurant", "restaurant_staff"] | None = None
    profile_data: dict[str, Any] | None = None


class LinkGoogleAccountSchema(BaseModel):
    id_token: str


class LogoutSchema(BaseModel):
    refresh: str


class TokenRefreshSchema(BaseModel):
    refresh: str


class PasswordResetRequestSchema(BaseModel):
    email: EmailStr


class SetNewPasswordSchema(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access: str
    refresh: str
    token_type: str = "bearer"


class UserProfileResponse(BaseModel):
    """Top-level user record returned with tokens and from /auth/profile."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    phone: str | None
    username: str
    first_name: str
    last_name: str
    user_type: str
    auth_provider: str
    is_verified: bool
    is_active: bool
    is_staff: bool
    is_superuser: bool
    google_id: str | None = None
    last_login: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    profile: dict[str, Any] | None = None


class UserProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    phone: str | None = Field(default=None, pattern=r"^\+[1-9]\d{1,14}$")
    profile_data: dict[str, Any] | None = None


class AuthResponse(BaseModel):
    access: str
    refresh: str
    user: UserProfileResponse
    can_link_google: bool = True


class VerifyEmailResponse(BaseModel):
    """Returned when an OTP is verified but no account exists yet."""

    verified: bool = True
    user_exists: bool
    requires_registration: bool
    email: str | None = None
    phone: str | None = None


class NotificationPreferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    receive_push: bool
    receive_email: bool
    promotions_and_offers: bool
    new_restaurants: bool
    review_reminders: bool


class NotificationPreferenceUpdate(BaseModel):
    receive_push: bool | None = None
    receive_email: bool | None = None
    promotions_and_offers: bool | None = None
    new_restaurants: bool | None = None
    review_reminders: bool | None = None


class DeviceRegisterSchema(BaseModel):
    registration_id: str = Field(min_length=1, max_length=512)
    platform: Literal["android", "ios", "web"]


class MessageResponse(BaseModel):
    message: str
