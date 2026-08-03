from sqlalchemy import create_engine, text, inspect, func
from sqlalchemy.exc import OperationalError
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.core_data import Category, SubCategory, Tag

CATEGORY_SEED_DATA = [
    {
        "category": "SCHOOLS",
        "subcategories": [
            # "Show All",
            "Nurseries",
            "Kindergartens",
            "Primary Schools"
        ],
        "tags": [
            "Montessori Method",
            "Steiner Method",
            "Bilingual",
            "English",
            "Nature",
            "Outdoor",
            "On-site Cafeteria",
            "Organic Meals",
            "Inclusive",
            "Full Time",
            "Part Time",
            "Preschool Class",
            "After School Care",
            "Accessible for Disabilities/Strollers",
            "Parking",
            "Garden",
            "School Transport",
            "Summer Camp"
        ]
    },
    {
        "category": "HEALTH",
        "subcategories": [
            # "Show All",
            "Pediatricians",
            "Pregnancy & Motherhood",
            "Child Development & Learning",
            "Osteopathy & Rehabilitation",
            "Dentistry",
            "Family Consulting"
        ],
        "tags": [
            "Public Healthcare",
            "Private",
            "Online",
            "In Person",
            "Newborns",
            "Premature Babies",
            "Breastfeeding",
            "Weaning",
            "Sleep",
            "Language Development",
            "Learning",
            "Autism",
            "ADHD",
            "Learning Disabilities",
            "Postpartum",
            "Pregnancy",
            "Rehabilitation",
            "Pediatric Care",
            "Ophthalmologist",
            "Orthoptist",
            "Accessible for Disabilities/Strollers",
            "Parking"
        ]
    },
    {
        "category": "COURSES, ACTIVITIES & EXPERIENCES",
        "subcategories": ["sub-course", "sub-activity", "sub-experience"],
        "tags": [
            "0-3 Years",
            "3-6 Years",
            "6-10 Years",
            "10+ Years",
            "Parent & Child",
            "Indoor",
            "Outdoor",
            "English",
            "Creativity",
            "Technology",
            "Science",
            "Robotics",
            "Animals",
            "Nature",
            "Hands-on Activities",
            "Weekend",
            "After School",
            "Summer",
            "Inclusive",
            "Free Trial",
            "Sensitive Children"
        ]
    },
    {
        "category": "SPORTS",
        "subcategories": ["sub-sport"],
        "tags": [
            "0-3 Years",
            "3-6 Years",
            "6-10 Years",
            "Indoor",
            "Outdoor",
            "Inclusive",
            "Individual",
            "Team",
            "Parent & Child",
            "Water Activities",
            "Summer",
            "Year Round",
            "Parking"
        ]
    },
    {
        "category": "PARTIES",
        "subcategories": [
            # "Show All",
            "Entertainment, Face Painting & Decorations",
            "Cake Designers & Catering",
            "Venues & Locations",
            "Photographers & Videographers",
            "Other"
        ],
        "tags": [
            "Indoor",
            "Outdoor",
            "Catering Included",
            "Parking",
            "Bouncy Castles",
            "Entertainment"
        ]
    },
    {
        "category": "FAMILY FRIENDLY LOCALS",
        "subcategories": ["sub-local"],
        "tags": [
            "Changing Table",
            "High Chairs",
            "Kids Menu",
            "Play Area",
            "Breastfeeding Area",
            "Accessible for Strollers/Disabilities",
            "Parking",
            "Outdoor Seating"
        ]
    },
    {
        "category": "PLAYGROUNDS",
        "subcategories": ["sub-playground"],
        "tags": [
            "Outdoor",
            "Indoor",
            "0-3 Years",
            "3-6 Years",
            "6-10 Years",
            "Picnic Area",
            "Toilets",
            "Café",
            "Parking",
            "Shade",
            "Water Features",
            "Inclusive",
            "Accessible for Strollers/Disabilities"
        ]
    },
    {
        "category": "OUTDOOR",
        "subcategories": ["sub-outdoor"],
        "tags": [
            "Walks",
            "Hiking",
            "Lakes",
            "Rivers",
            "Beaches",
            "Nature",
            "Culture",
            "Stroller Friendly",
            "Trekking",
            "Easy",
            "Moderate Difficulty",
            "Advanced",
            "Scenic Views",
            "Animals",
            "Picnic",
            "Shade",
            "Dog Friendly"
        ]
    },
    {
        "category": "SHOPPING",
        "subcategories": [
            # "Show All",
            "Clothing",
            "Toys & Books",
            "Equipment",
            "Maternity"
        ],
        "tags": [
            "Newborn",
            "Child",
            "Mom",
            "Second Hand",
            "Eco Friendly",
            "Handmade",
            "Made in Italy",
            "Gifts",
            "Car Equipment",
            "Home Equipment",
            "Baby Carriers",
            "Books",
            "Educational Toys",
            "Home Delivery",
            "Online Shop"
        ]
    },
    {
        "category": "FOR MOM",
        "subcategories": [
            # "Show All",
            "Fitness, Yoga & Pilates",
            "Wellness",
            "Maternity Photography",
            "Pre & Postpartum Specialists"
        ],
        "tags": [
            "Pregnancy",
            "Postpartum",
            "Mom & Baby",
            "Relaxation",
            "Wellness",
            "Fitness Recovery",
            "Drainage",
            "Massage",
            "Yoga",
            "Pilates",
            "Mindfulness",
            "Nutrition",
            "Beauty",
            "Self Care"
        ]
    },
    {
        "category": "EVENTS",
        "subcategories": [],
        "tags": [
            "Today",
            "Tomorrow",
            "This Weekend",
            "This Week",
            "This Month",
            "Free",
            "Paid",
            "0-3 Years",
            "3-6 Years",
            "6-10 Years",
            "Indoor",
            "Outdoor",
            "Workshop",
            "Show",
            "Reading",
            "Sports",
            "Nature",
            "Animals",
            "Moms",
            "Family"
        ]
    },
    {
        "category": "GIFTS",
        "subcategories": [
            # "Show All",
            "Experiences",
            "Products",
            "Special Occasions",
            "For Mom",
            "New Parents"
        ],
        "tags": [
            "Voucher",
            "Gift Card",
            "Course",
            "Toy",
            "New Baby",
            "Baptism",
            "First Birthday",
            "Birthday",
            "Celebration",
            "Personalized",
            "Digital",
            "Last Minute",
            "Local Gift",
            "Sustainable Gift",
            "Educational Gift",
            "Creative Gift",
            "Mom",
            "Dad",
            "Family",
            "Newborn",
            "Child",
            "Gift Box",
            "Shared Experience"
        ]
    }
]

def seed_taxonomy_data():
    db = SessionLocal()
    try:
        DEFAULT_CATEGORY_IMAGE = "uploads/defaults/default_activity.png"
        DEFAULT_SUBCATEGORY_IMAGE = "uploads/defaults/default_activity.png"
        for entry in CATEGORY_SEED_DATA:
            category_name = entry["category"].strip()
            category = db.query(Category).filter(func.lower(Category.name) == category_name.lower()).first()
            if not category:
                category = Category(name=category_name, image_url=DEFAULT_CATEGORY_IMAGE)
                db.add(category)
                db.flush()

            for sub_name in entry.get("subcategories", []):
                normalized = sub_name.strip()
                if not normalized:
                    continue
                exists = db.query(SubCategory).filter(
                    SubCategory.category_id == category.id,
                    func.lower(SubCategory.name) == normalized.lower()
                ).first()
                if not exists:
                    db.add(SubCategory(name=normalized, category_id=category.id, image_url=DEFAULT_SUBCATEGORY_IMAGE))

            for tag_name in entry.get("tags", []):
                normalized = tag_name.strip()
                if not normalized:
                    continue

                exists = db.query(Tag).filter(
                    Tag.category_id == category.id,
                    func.lower(Tag.name) == normalized.lower()
                ).first()
                if not exists:
                    db.add(Tag(name=normalized, category_id=category.id))

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_database():
    """Checks if the target database exists and creates it if it doesn't."""
    db_name = settings.DATABASE_URL.split('/')[-1]
    postgres_url = settings.DATABASE_URL.replace(f'/{db_name}', '/postgres')
    
    try:
        engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            result = connection.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            db_exists = result.scalar_one_or_none()

            if not db_exists:
                print(f"Database '{db_name}' not found. Creating it...")
                connection.execute(text(f'CREATE DATABASE "{db_name}"'))
                print(f"Database '{db_name}' created successfully.")
            else:
                print(f"Database '{db_name}' already exists.")

    except Exception as e:
        print(f"Error during database initialization: {e}")
        raise

def sync_database_schema(engine):
    """
    Automatically checks the 'users' table and adds any missing columns.
    This saves you from having to manually run SQL commands in the database.
    """
    inspector = inspect(engine)
    
    # Check if the users table has been created yet
    if inspector.has_table("users"):
        # Get a list of all columns currently in the database
        existing_columns = [col['name'] for col in inspector.get_columns("users")]
        
        # Dictionary of columns that SHOULD exist for onboarding
        missing_columns_check = {
            "role": "VARCHAR",
            "location_name": "VARCHAR",
            "lat": "FLOAT",
            "lng": "FLOAT",
            "profile_image_url": "VARCHAR",
            "onboarding_completed": "BOOLEAN DEFAULT FALSE"
        }
        
        with engine.begin() as conn:
            for col_name, col_type in missing_columns_check.items():
                if col_name not in existing_columns:
                    print(f"Auto-Migration: Adding missing column '{col_name}' to users table...")
                    # Run the ALTER TABLE command automatically via Python
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};"))