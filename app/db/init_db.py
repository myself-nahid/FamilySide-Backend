from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import OperationalError
from app.core.config import settings

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