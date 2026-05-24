from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.schemas.auth_schema import (
    RefreshTokenRequest, SignUpRequest, LoginRequest, ForgotPasswordRequest, 
    ResetPasswordRequest, ChangePasswordRequest, 
    APIResponse, TokenData
)
from app.core.security import (
    get_password_hash, verify_password, create_access_token, create_refresh_token, create_password_reset_token
)
from app.api.deps import get_db, get_current_user 
from app.models.user import OTPVerification, User
from pydantic import BaseModel
import random
from app.core.config import settings
from jose import jwt

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/signup", response_model=APIResponse[TokenData])
async def signup(payload: SignUpRequest, db: Session = Depends(get_db)):
    # 1. Check if user exists
    user_exists = db.query(User).filter(User.email == payload.email).first()
    if user_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email already exists."
        )
    
    # 2. Create User
    new_user = User(
        full_name=payload.name,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        user_type=payload.user_type,
        auth_provider="local"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # 3. Generate Token
    # access_token = create_access_token(subject=new_user.id)
    # refresh_token = create_refresh_token(subject=new_user.id)
    return APIResponse(
        status="success",
        message="Account created successfully",
        data=TokenData(
            # access_token=access_token,
            # refresh_token=refresh_token,
            # user_id=new_user.id,
            name=new_user.full_name,
            email=new_user.email
        )
    )

@router.post("/login", response_model=APIResponse[TokenData])
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    # 1. Find User
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # 2. Verify Password
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    # 3. Generate Token
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)
    return APIResponse(
        status="success",
        message="Login successful",
        data=TokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            # user_id=user.id,
            name=user.full_name,
            email=user.email
        )
    )

@router.post("/refresh", response_model=APIResponse[dict])
async def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    try:
        # Decode and verify the refresh token
        payload_data = jwt.decode(payload.refresh_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload_data.get("sub")
        token_type = payload_data.get("type")
        
        if user_id is None or token_type != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")
            
        # Generate a NEW access token
        new_access_token = create_access_token(subject=user_id)
        
        return APIResponse(
            status="success",
            message="Token refreshed",
            data={"access_token": new_access_token}
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Refresh token expired or invalid")

@router.post("/admin/login", response_model=APIResponse[TokenData])
async def admin_login(payload: LoginRequest, db: Session = Depends(get_db)):
    # 1. Find User
    user = db.query(User).filter(User.email == payload.email).first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied. Admins only.")
    
    # 2. Verify Password
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    
    # 3. Generate BOTH tokens (to satisfy the updated TokenData schema)
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id) # <--- Make sure this is generated!
    
    # 4. Return TokenData with all required fields
    return APIResponse(
        status="success",
        message="Admin login successful",
        data=TokenData(
            access_token=access_token,
            refresh_token=refresh_token, 
            user_id=user.id,             
            name=user.full_name,
            email=user.email
        )
    )

@router.post("/forgot-password", response_model=APIResponse[None])
async def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        # Security best practice: Do not reveal if email exists or not
        return APIResponse(
            status="success",
            message="If your email is registered, you will receive a password reset link."
        )
    
    # Generate secure short-lived token
    reset_token = create_password_reset_token(email=user.email)
    
    # TODO: Integrate Email Service (e.g., SendGrid, AWS SES)
    # send_reset_email(user.email, reset_token)
    print(f"Mock Email Sent -> Token: {reset_token}")
    
    return APIResponse(
        status="success",
        message="If your email is registered, you will receive a password reset link."
    )

@router.post("/reset-password", response_model=APIResponse[None])
async def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        from jose import jwt
        from app.core.config import settings  # <-- IMPORT SETTINGS HERE
        
        # Verify Token using settings
        payload_data = jwt.decode(payload.token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload_data.get("sub")
        token_type = payload_data.get("type")
        
        if email is None or token_type != "reset":
            raise ValueError("Invalid token")
            
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset token"
        )
        
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Update password
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    
    return APIResponse(
        status="success",
        message="Password has been reset successfully. You can now login."
    )

@router.post("/change-password", response_model=APIResponse[None])
async def change_password(
    payload: ChangePasswordRequest, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # Protected Route
):
    """
    Matches Image 8 ("Create New Password"). Requires user to be logged in.
    """
    # Verify old password
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password"
        )
        
    # Prevent reusing the same password
    if payload.current_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as the current password"
        )
        
    # Update password
    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    
    return APIResponse(
        status="success",
        message="Password changed successfully."
    )

class VerifyOTPRequest(BaseModel):
    email: str
    otp: str

@router.post("/verify-otp")
async def verify_otp(payload: VerifyOTPRequest, db: Session = Depends(get_db)):
    # 1. Query OTP table for this email and code
    record = db.query(OTPVerification).filter(
        OTPVerification.email == payload.email,
        OTPVerification.otp_code == payload.otp
    ).first()
    
    if not record:
        raise HTTPException(status_code=400, detail="Invalid code")
    
    # 2. Return success, frontend then navigates to "Reset Password" screen
    return {"status": "success", "message": "Code verified"}

@router.patch("/account/upgrade-to-provider")
async def upgrade_to_provider(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.user_type == "provider":
        raise HTTPException(status_code=400, detail="Already a provider")
    
    current_user.user_type = "provider"
    db.commit()
    return {"message": "Account upgraded successfully"}