from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.api.deps import get_db, get_current_admin
from app.models.user import User, Child
from app.models.core_data import PlatformItem, Category
from app.schemas.auth_schema import APIResponse, ChangePasswordRequest
from datetime import datetime, timedelta
from sqlalchemy import func, and_
from app.schemas.admin_schema import (
    DashboardOverviewResponse, TrendMetric, StatusDistribution,
    FlaggedItemListItem, PendingApprovalListItem, UpcomingEventListItem,
    ChartDataResponse, ChartDataPoint
)
from app.schemas.admin_schema import (
    DashboardStatsResponse, UserActionRequest, 
    ItemStatusUpdateRequest, CreateItemRequest, AdminProfileUpdateRequest
)
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

# 1. Dashboard Overview
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


# INTERACTIVE LINE CHART FILTERING API (Activity Overview)
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

# 2. USER MANAGEMENT 
@router.get("/users")
async def list_users(user_type: str = "all", db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    query = db.query(User)
    if user_type != "all":
        query = query.filter(User.user_type == user_type)
    return {"status": "success", "data": query.all()}

@router.patch("/users/{user_id}/status")
async def change_user_status(user_id: int, payload: UserActionRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # actions: block, activate, suspend
    if payload.action == "block":
        user.status = "Blocked"
    elif payload.action == "activate":
        user.status = "Active"
        
    db.commit()
    return {"status": "success", "message": f"User status updated to {user.status}"}

# 3. CONTENT APPROVALS & REJECTIONS 
@router.get("/items/pending")
async def get_pending_items(db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Matches the Notifications / To-Do Today approval queue"""
    items = db.query(PlatformItem).filter(PlatformItem.status == "pending").all()
    return {"status": "success", "data": items}

@router.patch("/items/{item_id}/status")
async def update_item_status(item_id: int, payload: ItemStatusUpdateRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    """Matches the 'Approve', 'Reject', and 'Block' buttons on item modals"""
    item = db.query(PlatformItem).filter(PlatformItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    item.status = payload.status # e.g., 'approved', 'rejected', 'blocked'
    db.commit()
    return {"status": "success", "message": f"Item {item.name} marked as {item.status}"}

# 4. CREATE CONTENT
@router.post("/items/create")
async def admin_create_item(payload: CreateItemRequest, db: Session = Depends(get_db), admin: User = Depends(get_current_admin)):
    new_item = PlatformItem(
        item_type=payload.item_type,
        name=payload.name,
        category_id=payload.category_id,
        location=payload.location,
        price=payload.price,
        description=payload.description,
        date=payload.date,
        start_time=payload.start_time,
        end_time=payload.end_time,
        website=payload.website,
        whatsapp=payload.whatsapp,
        instagram=payload.instagram,
        creator_id=admin.id,
        status="approved" # Admin creations are auto-approved
    )
    db.add(new_item)
    db.commit()
    return {"status": "success", "message": f"{payload.item_type.capitalize()} created successfully"}

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