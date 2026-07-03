from datetime import datetime
import math
from fastapi import Request
from typing import Optional

def calculate_distance_km(lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]) -> Optional[float]:
    """
    Calculates distance between two coordinates in kilometers using Haversine formula.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
        
    R = 6371.0 # Earth radius in kilometers
    
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (math.sin(dlat / 2) * math.sin(dlat / 2) +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) * math.sin(dlon / 2))
    
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    
    return round(distance, 2)

def get_full_url(request: Request, path: Optional[str]) -> Optional[str]:
    # We add the 'r' prefix here to prevent the (unicode error)
    r"""
    Converts a database path like 'uploads/profiles\user_1.jpg' 
    into a valid absolute URL like 'http://localhost:8015/uploads/profiles/user_1.jpg'
    """
    if not path:
        return None
    
    # 1. If it's already a full URL (Social Login), return it
    if path.startswith("http"):
        return path

    # 2. Fix Windows backslashes to forward slashes for the web
    clean_path = path.replace("\\", "/")
    
    # 3. Ensure the path doesn't start with a slash for clean concatenation
    clean_path = clean_path.lstrip("/")

    # 4. Build the base URL
    base_url = str(request.base_url)
    
    # Force HTTP for local development to avoid SSL errors in browser/Flutter
    if "localhost" in base_url or "127.0.0.1" in base_url:
        base_url = base_url.replace("https://", "http://")

    return f"{base_url}{clean_path}"

def get_dynamic_time_ago(dt: datetime) -> str:
    """
    Converts a datetime into a dynamic string like '5 minutes ago' or '2 days ago'.
    """
    if not dt:
        return "Never updated"
        
    now = datetime.utcnow()
    diff = now - dt

    if diff.days == 0:
        if diff.seconds < 60:
            return "just now"
        if diff.seconds < 3600:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        hours = diff.seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
        
    if diff.days == 1:
        return "yesterday"
    
    if diff.days < 30:
        return f"{diff.days} days ago"
        
    return dt.strftime("%d %b %Y")