from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.schemas.auth_schema import (
    RefreshTokenRequest, SignUpRequest, LoginRequest, ForgotPasswordRequest, 
    ResetPasswordRequest, ChangePasswordRequest, 
    APIResponse, SocialLoginRequest, TokenData
)
from app.core.security import (
    get_password_hash, verify_password, create_access_token, create_refresh_token, create_password_reset_token
)
from app.api.deps import get_db, get_current_user 
from app.models.user import OTPVerification, User
from pydantic import BaseModel
from fastapi import BackgroundTasks
from app.services.email_service import send_otp_email
from app.models.user import PasswordResetOTP
import random
from app.core.config import settings
from jose import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import httpx 
from jose import jwt as jose_jwt

router = APIRouter(prefix="/auth", tags=["Authentication"])

"""signup, login, social login, refresh token, forgot/reset password, change password, admin login"""
# 1. SIGNUP
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
    access_token = create_access_token(subject=new_user.id)
    refresh_token = create_refresh_token(subject=new_user.id)
    return APIResponse(
        status="success",
        message="Account created successfully",
        data=TokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=new_user.id,
            name=new_user.full_name,
            email=new_user.email,
            user_type=new_user.user_type
        )
    )

# 2. LOGIN (Normal Login)
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
            user_id=user.id,
            name=user.full_name,
            email=user.email,
            user_type=user.user_type
        )
    )

"""Google and Apple Social Login Helpers"""
# Mock implementations for development.
async def verify_google_token(token: str):
    # DEVELOPMENT MOCK: If send 'test_google_token', it bypasses Google Servers
    if token == "test_google_token":
        return {"email": "social_test@gmail.com", "name": "Mishuk Social", "provider_id": "google_123"}
        
    try:
        idinfo = id_token.verify_oauth2_token(
            token, 
            google_requests.Request(), 
            settings.GOOGLE_CLIENT_ID
        )
        return {
            "email": idinfo['email'],
            "name": idinfo.get('name', idinfo['email'].split('@')[0]),
            "provider_id": idinfo['sub']
        }
    except Exception as e:
        print(f"Google Auth Error: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google token")

async def verify_apple_token(token: str):
    # DEVELOPMENT MOCK: If you send 'test_apple_token'
    if token == "test_apple_token":
        return {"email": "apple_test@icloud.com", "name": "Apple User", "provider_id": "apple_123"}

    try:
        payload = jose_jwt.get_unverified_claims(token)
        
        # Security check: Ensure the token was actually meant for your app
        if payload.get("aud") != settings.APPLE_CLIENT_ID:
             raise ValueError("Token audience mismatch")

        return {
            "email": payload.get('email'),
            "name": "Apple User", # Apple only provides name on first login
            "provider_id": payload.get('sub')
        }
    except Exception as e:
        print(f"Apple Auth Error: {e}")
        raise HTTPException(status_code=401, detail="Invalid Apple token")
    

# production solutions    
# async def verify_google_token(token: str):
#     try:
#         # Use settings.GOOGLE_CLIENT_ID instead of a string
#         idinfo = id_token.verify_oauth2_token(
#             token, 
#             google_requests.Request(), 
#             settings.GOOGLE_CLIENT_ID
#         )
#         return {
#             "email": idinfo['email'],
#             "name": idinfo.get('name', idinfo['email'].split('@')[0]),
#             "provider_id": idinfo['sub']
#         }
#     except Exception:
#         raise HTTPException(status_code=401, detail="Invalid Google token")

# async def verify_apple_token(token: str):
#     try:
#         # In a full production check, you'd use settings.APPLE_CLIENT_ID 
#         # to verify the 'aud' (audience) claim of the Apple JWT
#         payload = jose_jwt.get_unverified_claims(token)
        
#         # Security check: Ensure the token was actually meant for your app
#         if payload.get("aud") != settings.APPLE_CLIENT_ID:
#              raise ValueError("Token audience mismatch")

#         return {
#             "email": payload.get('email'),
#             "name": "Apple User",
#             "provider_id": payload.get('sub')
#         }
#     except Exception:
#         raise HTTPException(status_code=401, detail="Invalid Apple token")

# 3. SOCIAL LOGIN
@router.post("/social-login", response_model=APIResponse[TokenData])
async def social_auth(payload: SocialLoginRequest, db: Session = Depends(get_db)):
    # 1. Verify the token with the provider
    if payload.provider == "google":
        user_data = await verify_google_token(payload.id_token)
    else:
        user_data = await verify_apple_token(payload.id_token)

    # 2. Check if user exists
    user = db.query(User).filter(User.email == user_data["email"]).first()

    if not user:
        # Create new user if they don't exist
        user = User(
            full_name=user_data["name"],
            email=user_data["email"],
            auth_provider=payload.provider.value,
            user_type=payload.user_type.value,
            onboarding_completed=False,
            hashed_password=None # Social users don't have a local password
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    # 3. Generate our system tokens
    access_token = create_access_token(subject=user.id)
    refresh_token = create_refresh_token(subject=user.id)

    return APIResponse(
        status="success",
        message=f"Logged in via {payload.provider.value}",
        data=TokenData(
            access_token=access_token,
            refresh_token=refresh_token,
            user_id=user.id,
            name=user.full_name,
            email=user.email
        )
    )

# 4. REFRESH TOKEN
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

# 5. ADMIN LOGIN
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

# 6. FORGOT PASSWORD, VERIFY OTP & RESET PASSWORD
@router.post("/forgot-password", response_model=APIResponse[None])
async def forgot_password(
    payload: ForgotPasswordRequest, 
    background_tasks: BackgroundTasks, # Use background task so user doesn't wait
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        # Standard security: return success even if user doesn't exist
        return APIResponse(status="success", message="If registered, an OTP has been sent.")

    # 1. Generate 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"
    expiry = datetime.utcnow() + timedelta(minutes=15)

    # 2. Save/Update OTP in DB
    db.query(PasswordResetOTP).filter(PasswordResetOTP.email == payload.email).delete()
    db_otp = PasswordResetOTP(email=payload.email, otp_code=otp, expires_at=expiry)
    db.add(db_otp)
    db.commit()

    # 3. Send Email in Background
    background_tasks.add_task(send_otp_email, payload.email, otp)

    return APIResponse(status="success", message="OTP sent to your email.")

@router.post("/verify-otp", response_model=APIResponse[dict])
async def verify_otp(email: str, otp: str, db: Session = Depends(get_db)):
    """Matches the 6-digit code screen in UI"""
    record = db.query(PasswordResetOTP).filter(
        PasswordResetOTP.email == email,
        PasswordResetOTP.otp_code == otp
    ).first()

    if not record or record.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    # Mark as verified so reset-password knows the user passed this stage
    record.is_verified = True
    db.commit()

    return APIResponse(status="success", message="OTP verified successfully", data={"email": email})

@router.post("/reset-password", response_model=APIResponse[None])
async def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Final Step: Takes the email and new password"""
    # Verify the user actually passed the OTP step
    otp_record = db.query(PasswordResetOTP).filter(
        PasswordResetOTP.email == payload.email,
        PasswordResetOTP.is_verified == True
    ).first()

    if not otp_record:
        raise HTTPException(status_code=400, detail="Please verify your email via OTP first.")

    user = db.query(User).filter(User.email == payload.email).first()
    user.hashed_password = get_password_hash(payload.new_password)
    
    # Cleanup: Delete OTP records after successful reset
    db.query(PasswordResetOTP).filter(PasswordResetOTP.email == payload.email).delete()
    db.commit()

    return APIResponse(status="success", message="Password reset successful. You can now login.")

# 7. CHANGE PASSWORD (Protected Route)
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

# 8. UPGRADE ACCOUNT (Family -> Provider)
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

# 9. DELETE ACCOUNT
@router.delete("/account/delete")
async def delete_account(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted successfully"}