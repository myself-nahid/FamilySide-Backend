from enum import Enum

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, Generic, TypeVar

T = TypeVar("T")

class APIResponse(BaseModel, Generic[T]):
    status: str
    message: str
    data: Optional[T] = None

class UserType(str, Enum):
    family = "family"
    provider = "provider"


class SignUpRequest(BaseModel):
    name: str = Field(..., min_length=2, example="John Doe")
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=72)
    user_type: UserType = Field(..., example="family")

    @validator("password")
    def password_max_72_bytes(cls, v):
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes in UTF-8 encoding.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=72)

    @validator("password")
    def password_max_72_bytes(cls, v):
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes in UTF-8 encoding.")
        return v

class SocialAuthProvider(str, Enum):
    google = "google"
    apple = "apple"

class SocialLoginRequest(BaseModel):
    id_token: str
    provider: SocialAuthProvider
    user_type: Optional[UserType] = UserType.family # Required for new signups

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str 
    new_password: str = Field(..., min_length=6, max_length=72)

    @validator("new_password")
    def password_max_72_bytes(cls, v):
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes in UTF-8 encoding.")
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=72)
    new_password: str = Field(..., min_length=6, max_length=72)

    @validator("current_password", "new_password")
    def password_max_72_bytes(cls, v):
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password cannot exceed 72 bytes in UTF-8 encoding.")
        return v

class TokenData(BaseModel):
    access_token: str
    refresh_token: str
    # token_type: str = "bearer"
    user_id: int
    name: str
    email: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str