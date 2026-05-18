from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Generic, TypeVar

T = TypeVar("T")

# Standard API Response Wrapper
class APIResponse(BaseModel, Generic[T]):
    status: str
    message: str
    data: Optional[T] = None

# Request Schemas
class SignUpRequest(BaseModel):
    name: str = Field(..., min_length=2, example="John Doe")
    email: EmailStr
    password: str = Field(..., min_length=6)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str 
    new_password: str = Field(..., min_length=6)

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)

# Response Data Schemas
class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    name: str
    email: str