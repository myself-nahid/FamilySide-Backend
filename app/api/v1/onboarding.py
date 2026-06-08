from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import List
from pathlib import Path
import os
import shutil

from app.api.deps import get_db, get_current_user
from app.models.user import SocialLink, User, Child, Interest
from app.schemas.auth_schema import APIResponse
from app.schemas.onboarding_schema import (
    BusinessSetupRequest, RoleUpdateRequest, ChildrenSetupRequest, 
    LocationUpdateRequest, InterestsUpdateRequest
)

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

@router.patch("/role", response_model=APIResponse[None])
async def set_role(
    payload: RoleUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.role = payload.role
    db.commit()
    return APIResponse(status="success", message="Role updated successfully")

@router.post("/children", response_model=APIResponse[None])
async def setup_children(
    payload: ChildrenSetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Clear existing children if re-doing onboarding
    db.query(Child).filter(Child.parent_id == current_user.id).delete()
    
    if payload.is_expecting:
        new_child = Child(
            parent_id=current_user.id,
            is_expecting=True,
            expected_due_date=payload.expected_due_date
        )
        db.add(new_child)
    else:
        for child_data in payload.children:
            new_child = Child(
                parent_id=current_user.id,
                is_expecting=False,
                name=child_data.name,
                dob=child_data.dob,
                gender=child_data.gender
            )
            db.add(new_child)
            
    db.commit()
    return APIResponse(status="success", message="Children details saved successfully")

# --- Helper Endpoint for Frontend to get the list of available interests ---
@router.get("/interests/list")
async def get_available_interests(db: Session = Depends(get_db)):
    interests = db.query(Interest).all()
    # Auto-populate some if empty (just for development convenience)
    if not interests:
        default_interests = ["Education", "Music", "Sports", "Dance", "Outdoor Play", "Coding"]
        for name in default_interests:
            db.add(Interest(name=name))
        db.commit()
        interests = db.query(Interest).all()
        
    return {"status": "success", "data": [{"id": i.id, "name": i.name} for i in interests]}

@router.post("/interests", response_model=APIResponse[None])
async def set_interests(
    payload: InterestsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Fetch the interest objects from DB
    selected_interests = db.query(Interest).filter(Interest.id.in_(payload.interest_ids)).all()
    
    current_user.interests = selected_interests
    db.commit()
    return APIResponse(status="success", message="Interests saved successfully")

@router.patch("/location", response_model=APIResponse[None])
async def set_location(
    payload: LocationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.location_name = payload.location_name
    current_user.lat = payload.lat
    current_user.lng = payload.lng
    db.commit()
    return APIResponse(status="success", message="Location saved successfully")

@router.post("/profile-image", response_model=APIResponse[None])
async def upload_profile_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Standardize Directory
    UPLOAD_DIR = Path("uploads/profiles")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    
    # 2. Secure Filename
    file_extension = file.filename.split(".")[-1]
    file_name = f"user_{current_user.id}.{file_extension}"
    file_path = UPLOAD_DIR / file_name # Uses correct OS slashes
    
    # 3. Save File
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 4. DATABASE FIX: Always store with forward slashes for URLs
    # We store the relative path: "uploads/profiles/user_3.jpg"
    url_path = str(file_path).replace("\\", "/") 
    
    current_user.profile_image_url = url_path
    current_user.onboarding_completed = True
    db.commit()
    
    return APIResponse(status="success", message="Profile image uploaded!")

@router.post("/business/social-links", response_model=APIResponse[None])
async def setup_business_links(
    payload: BusinessSetupRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Matches Image 3: "Help us to connect more about your business"
    """
    # 1. First, make sure we mark this user as a provider
    if current_user.user_type != "provider":
        current_user.user_type = "provider"
    
    # 2. Clear existing links to handle updates/edits cleanly
    db.query(SocialLink).filter(SocialLink.user_id == current_user.id).delete()
    
    # 3. Add all new links from the payload
    for link_data in payload.links:
        new_link = SocialLink(
            user_id=current_user.id,
            platform=link_data.platform.lower(),
            url=link_data.url
        )
        db.add(new_link)
        
    # Mark onboarding as complete for providers after this step
    current_user.onboarding_completed = True
    db.commit()
    
    return APIResponse(status="success", message="Business profile links saved successfully")

# Example of using user_type to control logic
@router.get("/onboarding/status")
async def get_onboarding_status(current_user: User = Depends(get_current_user)):
    if current_user.user_type == "family":
        return {"next_step": "set_child_details"}
    else:
        return {"next_step": "set_business_links"}