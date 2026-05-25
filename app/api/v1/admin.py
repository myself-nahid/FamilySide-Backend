from alembic.environment import Optional
from alembic.util import status
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.api.deps import get_db, get_current_admin
from app.models.user import User, Child
from app.models.core_data import PlatformItem, Category
from app.schemas.auth_schema import APIResponse, ChangePasswordRequest
from datetime import datetime, timedelta
from sqlalchemy import func, and_
import os
import shutil
import json
from app.schemas.admin_schema import (
    DashboardOverviewResponse, TrendMetric, StatusDistribution,
    FlaggedItemListItem, PendingApprovalListItem, UpcomingEventListItem,
    ChartDataResponse, ChartDataPoint
)
from app.schemas.admin_schema import (
    DashboardStatsResponse, UserActionRequest, 
    ItemStatusUpdateRequest, CreateItemRequest, AdminProfileUpdateRequest, UserDetailResponse, ChildResponse, NotificationItem, ItemReviewDetailResponse, UserDetailResponse, ActivityListItem, ActivityDetailResponse, CreateActivityRequest
)
from app.models.core_data import Notification
from app.core.security import get_password_hash, verify_password

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])

# Helper function to calculate Trend Metrics (This Week vs Last Week)
def calculate_trend(db: Session, query_base, date_field) -> TrendMetric:
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    # Count for this week (last 7 days)
    this_week_count = query_base.filter(date_field >= one_week_ago).count()
    # Count for previous week (7 to 14 days ago)
    last_week_count = query_base.filter(and_(date_field >= two_weeks_ago, date_field < one_week_ago)).count()

    total_count = query_base.count()

    if last_week_count == 0:
        percentage_change = 100.0 if this_week_count > 0 else 0.0
    else:
        percentage_change = round(((this_week_count - last_week_count) / last_week_count) * 100, 1)

    return TrendMetric(
        count=total_count,
        percentage_change=abs(percentage_change),
        is_increase=percentage_change >= 0
    )

"""
1. DASHBOARD OVERVIEW (Top Cards + Trends + Donut Chart + Bottom Lists)
"""

# 1.1 Dashboard Overview (Top Cards + Donut Chart + Bottom Lists)
@router.get("/dashboard/overview", response_model=APIResponse[DashboardOverviewResponse])
async def get_dashboard_overview(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """
    Returns the complete dashboard overview data including top stats, 
    donut chart metrics, and recent bottom tables.
    """
    now = datetime.utcnow()
    one_week_ago = now - timedelta(days=7)

    # 1. Top Static Cards
    pending_approvals = db.query(PlatformItem).filter(PlatformItem.status == "pending").count()
    flagged_reviews = db.query(PlatformItem).filter(PlatformItem.status == "flagged").count()
    new_providers_this_week = db.query(User).filter(and_(User.user_type == "provider", User.join_date >= one_week_ago)).count()

    # 2. Trend Metrics Cards (Week over Week)
    total_users_query = db.query(User).filter(User.user_type == "family")
    total_users_trend = calculate_trend(db, total_users_query, User.join_date)

    new_users_query = db.query(User).filter(User.user_type == "family")
    new_users_trend = calculate_trend(db, new_users_query, User.join_date)

    activities_query = db.query(PlatformItem).filter(PlatformItem.item_type == "activity")
    activities_trend = calculate_trend(db, activities_query, PlatformItem.created_at)

    events_query = db.query(PlatformItem).filter(PlatformItem.item_type == "event")
    events_trend = calculate_trend(db, events_query, PlatformItem.created_at)

    gifts_query = db.query(PlatformItem).filter(PlatformItem.item_type == "gift")
    gifts_trend = calculate_trend(db, gifts_query, PlatformItem.created_at)

    # 3. Items by Status (Donut Chart Percentages)
    total_items = db.query(PlatformItem).count() or 1 # Avoid division by zero
    approved_count = db.query(PlatformItem).filter(PlatformItem.status == "approved").count()
    pending_count = db.query(PlatformItem).filter(PlatformItem.status == "pending").count()
    rejected_count = db.query(PlatformItem).filter(PlatformItem.status == "rejected").count()
    flagged_count = db.query(PlatformItem).filter(PlatformItem.status == "flagged").count()

    status_dist = StatusDistribution(
        approved_pct=round((approved_count / total_items) * 100, 1),
        pending_pct=round((pending_count / total_items) * 100, 1),
        rejected_pct=round((rejected_count / total_items) * 100, 1),
        flagged_pct=round((flagged_count / total_items) * 100, 1)
    )

    # 4. Bottom Lists
    # A. Recent Flagged Items
    raw_flagged = db.query(PlatformItem).filter(PlatformItem.status == "flagged").order_by(PlatformItem.created_at.desc()).limit(4).all()
    recent_flagged_list = [
        FlaggedItemListItem(id=item.id, name=item.name, item_type=item.item_type.capitalize(), time_ago="1 hr ago")
        for item in raw_flagged
    ]

    # B. To-Do Today (Pending Approvals)
    raw_pending = db.query(PlatformItem).filter(PlatformItem.status == "pending").order_by(PlatformItem.created_at.desc()).limit(4).all()
    pending_todo_list = [
        PendingApprovalListItem(id=item.id, name=item.name, item_type=item.item_type.capitalize())
        for item in raw_pending
    ]

    # C. Upcoming Events
    raw_events = db.query(PlatformItem).filter(
        and_(PlatformItem.item_type == "event", PlatformItem.date >= now.date())
    ).order_by(PlatformItem.date.asc()).limit(4).all()
    
    upcoming_events_list = [
        UpcomingEventListItem(
            id=event.id, 
            name=event.name, 
            date=event.date.strftime("%d %b %Y") if event.date else "N/A",
            time=event.start_time.strftime("%I:%M %p") if event.start_time else "N/A"
        )
        for event in raw_events
    ]

    # Combine into unified response
    response_data = DashboardOverviewResponse(
        pending_approvals=pending_approvals,
        flagged_reviews=flagged_reviews,
        new_providers=new_providers_this_week,
        total_users=total_users_trend,
        new_users_this_week=new_users_trend,
        activities=activities_trend,
        events=events_trend,
        gifts=gifts_trend,
        status_distribution=status_dist,
        recent_flagged=recent_flagged_list,
        pending_todo=pending_todo_list,
        upcoming_events=upcoming_events_list
    )

    return APIResponse(status="success", message="Dashboard overview successfully loaded", data=response_data)


# 1.2 INTERACTIVE LINE CHART FILTERING API (Activity Overview) (Trends)
@router.get("/dashboard/chart", response_model=APIResponse[ChartDataResponse])
async def get_dashboard_chart(
    tab: str = "activity",        # activity, events, users, reviews
    timeframe: str = "year",      # year, month, week
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns data points dynamically calculated for the "Activity Overview" line chart.
    """
    points = []
    now = datetime.utcnow()

    # Determine query entity and target date field based on tab selected
    if tab in ["activity", "events", "reviews"]:
        entity = PlatformItem
        date_col = PlatformItem.created_at
        filter_type = "activity" if tab == "activity" else ("event" if tab == "events" else None)
    else:
        entity = User
        date_col = User.join_date
        filter_type = None

    # Filter query
    query = db.query(entity)
    if filter_type:
        query = query.filter(PlatformItem.item_type == filter_type)

    # Grouping logic depending on timeframe
    if timeframe == "year":
        # Group by Month (1 to 12) for the current year
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        for i, month_label in enumerate(months, start=1):
            count = query.filter(
                and_(
                    func.extract('year', date_col) == now.year,
                    func.extract('month', date_col) == i
                )
            ).count()
            points.append(ChartDataPoint(label=month_label, value=count))

    elif timeframe == "month":
        # Group by Weeks of the current month
        for week_num in range(1, 5):
            start_day = (week_num - 1) * 7 + 1
            end_day = week_num * 7
            count = query.filter(
                and_(
                    func.extract('year', date_col) == now.year,
                    func.extract('month', date_col) == now.month,
                    func.extract('day', date_col) >= start_day,
                    func.extract('day', date_col) <= end_day
                )
            ).count()
            points.append(ChartDataPoint(label=f"Week {week_num}", value=count))

    elif timeframe == "week":
        # Group by Days of the current week (Mon-Sun)
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        start_of_week = now - timedelta(days=now.weekday())
        for i, day_label in enumerate(days):
            target_date = start_of_week + timedelta(days=i)
            count = query.filter(
                func.date(date_col) == target_date.date()
            ).count()
            points.append(ChartDataPoint(label=day_label, value=count))

    return APIResponse(
        status="success", 
        message="Chart data loaded", 
        data=ChartDataResponse(tab=tab, timeframe=timeframe, points=points)
    )


# 1.3 VIEW ALL FLAGGED ITEMS (Matches "Recent flagged items -> View all")
@router.get("/items/flagged", response_model=APIResponse[dict])
async def get_all_flagged_items(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated, searchable list of all flagged items on the platform.
    """
    query = db.query(PlatformItem).filter(PlatformItem.status == "flagged")
    
    # Enable searching by item name if search query is provided
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    total_count = query.count()
    
    # Paginate using offset and limit
    offset = (page - 1) * limit
    items = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "item_type": item.item_type.capitalize(),
                "created_at": item.created_at.strftime("%Y-%m-%d") if item.created_at else None,
                "location": item.location
            } for item in items
        ]
    }
    
    return APIResponse(status="success", message="Flagged items fetched", data=pagination_data)


# 1.4 VIEW ALL PENDING APPROVALS (Matches "To do today -> View all")
@router.get("/items/pending/all", response_model=APIResponse[dict])
async def get_all_pending_approvals(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated, searchable list of all pending approvals on the platform.
    """
    query = db.query(PlatformItem).filter(PlatformItem.status == "pending")
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    total_count = query.count()
    offset = (page - 1) * limit
    items = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "item_type": item.item_type.capitalize(),
                "created_at": item.created_at.strftime("%Y-%m-%d") if item.created_at else None,
                "location": item.location
            } for item in items
        ]
    }
    
    return APIResponse(status="success", message="Pending approvals fetched", data=pagination_data)


# 1.5 VIEW ALL UPCOMING EVENTS (Matches "Upcoming Events -> View all")
@router.get("/items/upcoming/all", response_model=APIResponse[dict])
async def get_all_upcoming_events_paginated(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated, searchable list of all approved upcoming events,
    sorted by date ascending (closest events first).
    """
    now = datetime.utcnow()
    query = db.query(PlatformItem).filter(
        and_(
            PlatformItem.item_type == "event",
            PlatformItem.status == "approved",
            PlatformItem.date >= now.date()
        )
    )
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    total_count = query.count()
    offset = (page - 1) * limit
    items = query.order_by(PlatformItem.date.asc()).offset(offset).limit(limit).all()
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": event.id,
                "name": event.name,
                "date": event.date.strftime("%d %b %Y") if event.date else "N/A",
                "time": event.start_time.strftime("%I:%M %p") if event.start_time else "N/A",
                "location": event.location,
                "price": event.price
            } for event in items
        ]
    }
    
    return APIResponse(status="success", message="Upcoming events fetched", data=pagination_data)

"""
2. USER MANAGEMENT 
"""
# 2.1 LIST USERS - PAGINATED & FILTERED
@router.get("/users", response_model=APIResponse[dict])
async def get_users_paginated(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,         # Search by Name or Email
    user_type: Optional[str] = "all",     # all, family, provider
    status: Optional[str] = None,         # Active, Suspended, Blocked
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated list of all system users. 
    Supports full search queries and strict administrative filtering.
    """
    query = db.query(User)
    
    # Apply Filters
    if user_type and user_type != "all":
        query = query.filter(User.user_type == user_type)
        
    if status:
        query = query.filter(User.status == status)
        
    if search:
        query = query.filter(
            (User.full_name.ilike(f"%{search}%")) | 
            (User.email.ilike(f"%{search}%"))
        )
        
    total_count = query.count()
    offset = (page - 1) * limit
    
    # Order by newest users first
    users = query.order_by(User.join_date.desc()).offset(offset).limit(limit).all()
    
    # Map users to matching UI table columns
    user_list = [
        {
            "id": u.id,
            "name": u.full_name,
            "email": u.email,
            "user_type": u.user_type.capitalize() if u.user_type else "User",
            "location": u.location_name or "New work, UAS",
            "join_date": u.join_date.strftime("%d/%m/%Y") if u.join_date else "N/A",
            "subscription": u.subscription_plan or "Free",  
            "status": u.status or "Active"                  
        }
        for u in users
    ]
    
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "users": user_list
    }
    
    return APIResponse(status="success", message="Users fetched", data=pagination_data)


# 2.2 DETAILED USER REVIEW MODAL
@router.get("/users/{user_id}", response_model=APIResponse[UserDetailResponse])
async def get_user_detail_review(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Fetches the deep profile of a user, including total platform metrics, 
    their contributor level, and list of registered children.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    # Query actual platform metrics
    activities_created = db.query(PlatformItem).filter(
        PlatformItem.creator_id == user_id, 
        PlatformItem.item_type == "activity"
    ).count()
    
    # Dynamic calculations for the review modal stats card
    mock_reviews = 32       # Replace with db.query(Review).filter(...).count()
    mock_saved = 12         # Replace with db.query(Bookmark).filter(...).count()
    contributor_level = "Top 9%" # Logical algorithm based on reviews
    
    # Map Children relation (Image 1)
    children_data = [
        ChildResponse(
            id=child.id,
            name=child.name or "Unnamed",
            dob=child.dob.strftime("%d/%m/%Y") if child.dob else "N/A",
            gender=child.gender or "Male"
        )
        for child in user.children
    ]
    
    response_data = UserDetailResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role or "Father",
        join_date=user.join_date.strftime("%d/%m/%Y") if user.join_date else "N/A",
        location_name=user.location_name or "New work, UAS",
        status=user.status or "Active",                      
        subscription_plan=user.subscription_plan or "Free",  
        reviews_count=mock_reviews,
        activities_count=activities_created,
        saved_items_count=mock_saved,
        contributor_level=contributor_level,
        children=children_data
    )
    
    return APIResponse(status="success", message="User review details fetched", data=response_data)


# 2.3 BLOCK/SUSPEND/ACTIVATE ACTION 
@router.patch("/users/{user_id}/action", response_model=APIResponse[None])
async def update_user_status_action(
    user_id: int,
    payload: UserActionRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Processes administrative account actions (Block, Suspend, Activate).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        
    action_type = payload.action.lower()
    
    if action_type == "block":
        user.status = "Blocked"
        user.is_active = False
    elif action_type == "suspend":
        user.status = "Suspended"
        user.is_active = False
    elif action_type == "activate":
        user.status = "Active"
        user.is_active = True
    else:
        raise HTTPException(status_code=400, detail="Invalid action type.")
        
    db.commit()
    return APIResponse(status="success", message=f"User account status has been updated to {user.status}")
    

"""
3. NOTIFICATIONS
This section covers all notification-related endpoints, including fetching paginated notifications, viewing detailed item modals, and approving/rejecting items directly from notifications.
"""

# 3.1 GET PAGINATED NOTIFICATIONS
@router.get("/notifications", response_model=APIResponse[dict])
async def get_notifications_paginated(
    page: int = 1,
    limit: int = 10,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Returns a paginated list of all administrative notifications,
    ordered by the newest notifications first.
    """
    query = db.query(Notification)
    total_count = query.count()
    offset = (page - 1) * limit
    
    notifications = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()
    
    # Format dates into friendly UI formats (e.g. "Tuesday 2:00 PM")
    formatted_list = []
    for n in notifications:
        formatted_list.append({
            "id": n.id,
            "title": n.title,
            "subtitle": n.subtitle,
            "item_type": n.item_type,
            "item_id": n.item_id,
            "is_read": n.is_read,
            "time_label": n.created_at.strftime("%A %I:%M %p") if n.created_at else "Today"
        })
        
    pagination_data = {
        "total": total_count,
        "page": page,
        "limit": limit,
        "notifications": formatted_list
    }
    
    return APIResponse(status="success", message="Notifications fetched", data=pagination_data)


# 3.2 VIEW DETAILED ITEM MODAL
@router.get("/notifications/{notification_id}/view", response_model=APIResponse[ItemReviewDetailResponse])
async def view_notification_item_detail(
    notification_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Resolves a notification and returns the exact detailed structural layout 
    of the linked Item (Activity, Event, or Gift) to populate review modals.
    """
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    item = db.query(PlatformItem).filter(PlatformItem.id == notification.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Associated item no longer exists")
        
    # Mark notification as read
    notification.is_read = True
    db.commit()
    
    # Gather tags & categories safely
    tags = ["Indoor", "Ongoing", "Free"] # Default mock tags for UI display
    sub_categories = ["Doctors", "Nurseries", "Playgrounds"] # Mock sub-categories
    
    # Map the object dynamically based on what type of item it is
    detail = ItemReviewDetailResponse(
        id=item.id,
        item_type=item.item_type,
        name=item.name,
        creator_email=item.creator.email if item.creator else "abc@gmail.com",
        category=item.category.name if item.category else "Uncategorized",
        sub_categories=sub_categories,
        tags=tags,
        price=item.price,
        description=item.description,
        website=item.website,
        instagram_link=item.instagram,
        whatsapp_number=item.whatsapp,
        date=item.date.strftime("%d/%m/%Y") if item.date else None,
        time=item.start_time.strftime("%I:%M %p") if item.start_time else None
    )
    
    return APIResponse(status="success", message="Item details fetched successfully", data=detail)


# 3.3 APPROVE ITEM
@router.post("/notifications/{notification_id}/approve", response_model=APIResponse[None])
async def approve_notification_item(
    notification_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    item = db.query(PlatformItem).filter(PlatformItem.id == notification.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    # Approve Item
    item.status = "approved"
    
    # Remove from notifications list as action is complete
    db.delete(notification)
    db.commit()
    
    return APIResponse(status="success", message=f"{item.item_type.capitalize()} has been approved and is now live!")


# 3.4 REJECT ITEM (Matches Images 5 & 9 Reject flow)
@router.post("/notifications/{notification_id}/reject", response_model=APIResponse[None])
async def reject_notification_item(
    notification_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Rejects the item, changing its database status to 'rejected'
    and clearing it out of the active notifications table.
    """
    notification = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
        
    item = db.query(PlatformItem).filter(PlatformItem.id == notification.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    # Reject Item
    item.status = "rejected"
    
    # Remove from notifications list as action is complete
    db.delete(notification)
    db.commit()
    
    return APIResponse(status="success", message=f"{item.item_type.capitalize()} has been rejected successfully.")


"""4. ACTIVITY MANAGEMENT
This section includes all endpoints related to managing activities, including listing activities with pagination and search, viewing detailed activity modals, creating new activities, and deleting activities. These endpoints are designed to support the full lifecycle of activity management from the admin dashboard."""

# 4.1 GET ALL ACTIVITIES (Paginated + Searchable + Filter by Creator Type)
@router.get("/activities", response_model=APIResponse[dict])
async def get_activities_paginated(
    page: int = 1,
    limit: int = 10,
    search: Optional[str] = None,
    creator_type: Optional[str] = "all", # Filter by "Admin", "User", "Provider"
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    query = db.query(PlatformItem).filter(PlatformItem.item_type == "activity")
    
    if search:
        query = query.filter(PlatformItem.name.ilike(f"%{search}%"))
        
    # Join with User table to filter by creator type if needed
    if creator_type and creator_type != "all":
        query = query.join(User, PlatformItem.creator_id == User.id).filter(User.user_type == creator_type.lower())

    total_count = query.count()
    offset = (page - 1) * limit
    activities = query.order_by(PlatformItem.created_at.desc()).offset(offset).limit(limit).all()
    
    activity_list = []
    for activity in activities:
        creator_label = "Admin"
        if activity.creator:
            creator_label = activity.creator.user_type.capitalize() if activity.creator.user_type else "User"
            
        activity_list.append(ActivityListItem(
            id=activity.id,
            name=activity.name,
            created_by=creator_label,
            category=activity.category.name if activity.category else "Uncategorized",
            location=activity.location or "N/A",
            fee=activity.price or 0.0
        ))
        
    return APIResponse(
        status="success", 
        message="Activities fetched", 
        data={"total": total_count, "page": page, "limit": limit, "items": activity_list}
    )

# 4.2 VIEW ACTIVITY DETAILS 
@router.get("/activities/{activity_id}", response_model=APIResponse[ActivityDetailResponse])
async def get_activity_detail(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    activity = db.query(PlatformItem).filter(
        PlatformItem.id == activity_id, 
        PlatformItem.item_type == "activity"
    ).first()
    
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    creator_label = "Admin"
    if activity.creator:
        creator_label = activity.creator.user_type.capitalize() if activity.creator.user_type else "User"

    # Mock tags for MVP display purposes
    mock_tags = ["Education", "Indoor", "Paid"]

    detail = ActivityDetailResponse(
        id=activity.id,
        name=activity.name,
        image_url=activity.image_url,
        description=activity.description,
        website=activity.website,
        location=activity.location,
        created_by=creator_label,
        status=activity.status.capitalize(),
        date_added=activity.created_at.strftime("%d %b %Y") if activity.created_at else "N/A",
        whatsapp=activity.whatsapp,
        opening_days=activity.opening_days,
        opening_hours=activity.opening_hours,
        tags=mock_tags
    )
    
    return APIResponse(status="success", message="Activity details fetched", data=detail)

# 4.3 CREATE ACTIVITY
@router.post("/activities", response_model=APIResponse[None])
async def create_activity(
    # Core fields
    name: str = Form(...),
    location: str = Form(...),
    category_id: int = Form(...),
    price: float = Form(0.0),
    description: str = Form(...),
    
    # Optional text fields
    website: Optional[str] = Form(None),
    whatsapp: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    instagram: Optional[str] = Form(None),
    opening_days: Optional[str] = Form(None),
    opening_hours: Optional[str] = Form(None),
    
    # Multi-select fields (Sent as JSON strings from frontend)
    sub_categories: Optional[str] = Form(None), # e.g., '["Doctors", "Nurseries"]'
    tags: Optional[str] = Form(None),           # e.g., '["Indoor", "Paid"]'
    
    # Image Upload
    photo: Optional[UploadFile] = File(None),
    
    # Dependencies
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    # 1. Handle File Upload (If photo is provided)
    saved_image_path = None
    if photo:
        UPLOAD_DIR = "uploads/activities"
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        
        # Create a unique filename
        file_extension = photo.filename.split(".")[-1]
        file_name = f"activity_{datetime.utcnow().timestamp()}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, file_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(photo.file, buffer)
        saved_image_path = f"/{file_path}"

    # 2. Parse JSON strings back to Python lists
    parsed_sub_categories = []
    parsed_tags = []
    if sub_categories:
        try: parsed_sub_categories = json.loads(sub_categories)
        except: parsed_sub_categories = [sub_categories] # Fallback if standard string
        
    if tags:
        try: parsed_tags = json.loads(tags)
        except: parsed_tags = [tags]

    # 3. Save to Database
    new_activity = PlatformItem(
        item_type="activity",
        name=name,
        location=location,
        category_id=category_id,
        price=price,
        description=description,
        website=website,
        whatsapp=whatsapp,
        email=email,
        instagram=instagram,
        opening_days=opening_days,
        opening_hours=opening_hours,
        sub_categories=parsed_sub_categories, # Save as JSON
        tags=parsed_tags,                     # Save as JSON
        image_url=saved_image_path,           # Save the uploaded image URL
        creator_id=admin.id,
        status="approved" # Auto-approved by admin
    )
    
    db.add(new_activity)
    db.commit()
    
    return APIResponse(status="success", message="Activity created successfully with photo!")

# 4.4 DELETE ACTIVITY 
@router.delete("/activities/{activity_id}", response_model=APIResponse[None])
async def delete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    activity = db.query(PlatformItem).filter(PlatformItem.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    db.delete(activity)
    db.commit()
    
    return APIResponse(status="success", message="Activity deleted successfully")


# 4.5 BLOCK ACTIVITY 
@router.patch("/activities/{activity_id}/block", response_model=APIResponse[None])
async def block_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """
    Blocks an activity, making it invisible to end-users 
    but keeping it in the admin records.
    """
    activity = db.query(PlatformItem).filter(
        PlatformItem.id == activity_id, 
        PlatformItem.item_type == "activity"
    ).first()
    
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    if activity.status == "blocked":
        raise HTTPException(status_code=400, detail="Activity is already blocked")
        
    # Change status to blocked
    activity.status = "blocked"
    db.commit()
    
    return APIResponse(status="success", message=f"Activity '{activity.name}' has been blocked successfully.")

# 4.6 UNBLOCK ACTIVITY
@router.patch("/activities/{activity_id}/unblock", response_model=APIResponse[None])
async def unblock_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Restores a blocked activity back to approved status."""
    activity = db.query(PlatformItem).filter(
        PlatformItem.id == activity_id, 
        PlatformItem.item_type == "activity"
    ).first()
    
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
        
    activity.status = "approved"
    db.commit()
    
    return APIResponse(status="success", message=f"Activity '{activity.name}' has been restored.")


# 5. ADMIN SETTINGS
@router.patch("/settings/profile")
async def update_admin_profile(payload: AdminProfileUpdateRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    admin.full_name = payload.name
    admin.email = payload.email
    admin.phone_number = payload.phone_number
    db.commit()
    return {"status": "success", "message": "Profile updated"}

@router.patch("/settings/security")
async def update_admin_password(payload: ChangePasswordRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    if not verify_password(payload.current_password, admin.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect current password")
    
    admin.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"status": "success", "message": "Password updated successfully"}