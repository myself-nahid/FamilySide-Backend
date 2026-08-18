#!/usr/bin/env python3
"""Run cleanup SQL against the database.

Usage:
  python scripts/cleanup_nan.py         # dry-run (prints SQL statements)
  python scripts/cleanup_nan.py --apply # actually executes statements

The script expects a `DATABASE_URL` environment variable (SQLAlchemy URL).
Example: export DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname
"""
import os
import argparse
from sqlalchemy import create_engine, text


SQL_STATEMENTS = [
    """
    UPDATE platform_items
    SET description = NULL
    WHERE description IS NOT NULL AND lower(trim(description)) = 'nan';
    """,
    """
    UPDATE platform_items
    SET price = 0
    WHERE price IS NOT NULL AND isnan(price);
    """
]


def main(apply: bool = False):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL environment variable not set. Aborting.")
        return 1

    engine = create_engine(db_url)

    print("Database URL:", db_url)
    for s in SQL_STATEMENTS:
        print("--- Statement ---")
        print(s.strip())
        print("-----------------")
    if not apply:
        print("\nDry-run mode. Use --apply to execute these statements.")
        return 0

    print("Executing statements...")
    with engine.begin() as conn:
        for s in SQL_STATEMENTS:
            conn.execute(text(s))

    print("Done.")
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Cleanup NaN values in platform_items')
    parser.add_argument('--apply', action='store_true', help='Execute statements (default is dry-run)')
    args = parser.parse_args()
    raise SystemExit(main(apply=args.apply))
