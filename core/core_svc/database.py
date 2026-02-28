"""Database initialization and migration system."""

import os
import re
from pathlib import Path

import aiosqlite
from fastapi import Request


async def init_db(db_path: str) -> aiosqlite.Connection:
    """
    Initialize database connection and apply pending migrations.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        Configured aiosqlite connection with WAL mode and foreign keys enabled

    Process:
        1. Ensure parent directory exists
        2. Open connection and configure (WAL mode, foreign keys, row_factory)
        3. Read current schema version from PRAGMA user_version
        4. Scan migrations directory for pending SQL files
        5. Apply migrations in order, updating version after each
        6. Return configured connection
    """
    # Ensure parent directory exists
    parent_dir = os.path.dirname(db_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    # Open connection
    conn = await aiosqlite.connect(db_path)

    # Enable WAL mode for concurrent reads
    await conn.execute("PRAGMA journal_mode=WAL")

    # Enable foreign key constraints
    await conn.execute("PRAGMA foreign_keys=ON")

    # Set row factory to return Row objects (dict-like access)
    conn.row_factory = aiosqlite.Row

    # Read current schema version (0 for fresh database)
    async with conn.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
        current_version = row[0]

    # Find migrations directory relative to this file
    migrations_dir = Path(__file__).parent.parent / "migrations"

    # Scan for migration files matching pattern NNN_*.sql
    migration_pattern = re.compile(r"^(\d{3})_.*\.sql$")
    pending_migrations = []

    if migrations_dir.exists():
        for file_path in migrations_dir.iterdir():
            if file_path.is_file():
                match = migration_pattern.match(file_path.name)
                if match:
                    migration_number = int(match.group(1))
                    if migration_number > current_version:
                        pending_migrations.append((migration_number, file_path))

    # Sort migrations by number
    pending_migrations.sort(key=lambda x: x[0])

    # Apply pending migrations
    for migration_number, migration_file in pending_migrations:
        print(f"Applying migration {migration_file.name}...")

        # Read migration SQL
        sql_content = migration_file.read_text()

        # Execute migration (executescript handles multiple statements)
        await conn.executescript(sql_content)

        # Update schema version
        await conn.execute(f"PRAGMA user_version = {migration_number}")
        await conn.commit()

        print(f"Migration {migration_file.name} applied successfully")

    return conn


async def get_db(request: Request) -> aiosqlite.Connection:
    """
    FastAPI dependency to retrieve database connection from app state.

    Args:
        request: FastAPI request object

    Returns:
        Database connection stored in request.app.state.db
    """
    return request.app.state.db
