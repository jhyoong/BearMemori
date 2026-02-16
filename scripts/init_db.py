"""
Standalone database initialization script.
Usage: python scripts/init_db.py [--db-path PATH]
"""
import argparse
import asyncio
import sys
sys.path.insert(0, '.')

async def main(db_path: str):
    from core.core.database import init_db
    db = await init_db(db_path)
    print(f"Database initialized at {db_path}")
    await db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="./life_organiser.db")
    args = parser.parse_args()
    asyncio.run(main(args.db_path))
