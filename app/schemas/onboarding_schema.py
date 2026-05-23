from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date
from enum import Enum

class RoleEnum(str, Enum):
    mother = "Mother"
    father = "Father"
    relative = "Relative"

class RoleUpdateRequest(BaseModel):
    role: RoleEnum

class ChildBase(BaseModel):
    name: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None

class ChildrenSetupRequest(BaseModel):
    is_expecting: bool
    children: Optional[List[ChildBase]] = []
    expected_due_date: Optional[date] = None

class InterestsUpdateRequest(BaseModel):
    interest_ids: List[int]

class LocationUpdateRequest(BaseModel):
    location_name: str
    lat: Optional[float] = None
    lng: Optional[float] = None