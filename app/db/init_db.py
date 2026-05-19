from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from app.core.config import settings

def init_database():
    """
    Checks if the target database exists and creates it if it doesn't.
    """
    # Extract the database name from the full URL
    db_name = settings.DATABASE_URL.split('/')[-1]

    # Create a connection URL to the default 'postgres' database
    # This is necessary because we can't connect to a non-existent database.
    postgres_url = settings.DATABASE_URL.replace(f'/{db_name}', '/postgres')
    
    try:
        engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
        with engine.connect() as connection:
            # Check if the database exists
            result = connection.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            db_exists = result.scalar_one_or_none()

            if not db_exists:
                print(f"Database '{db_name}' not found. Creating it...")
                # The 'CREATE DATABASE' command cannot be run inside a transaction block,
                # which is why we set isolation_level="AUTOCOMMIT" above.
                connection.execute(text(f'CREATE DATABASE "{db_name}"'))
                print(f"Database '{db_name}' created successfully.")
            else:
                print(f"Database '{db_name}' already exists.")

    except OperationalError as e:
        print(f"Error connecting to PostgreSQL server: {e}")
        # This could be a wrong password, host, or the server not running.
        # Exit or raise the exception to stop the application from proceeding.
        raise
    except Exception as e:
        print(f"An unexpected error occurred during database initialization: {e}")
        raise