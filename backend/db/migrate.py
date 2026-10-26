"""Tiny plain-SQL migration runner (no Alembic).

    python db/migrate.py            # apply pending migrations/*.sql
    python db/migrate.py --seed     # ... then apply seed.sql
    python db/migrate.py --reset --seed   # DROP SCHEMA public CASCADE first (dev only!)
"""
import os
import sys
from pathlib import Path

import psycopg

HERE = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/trials")


def main(argv):
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        if "--reset" in argv:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
            print("schema reset")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted((HERE / "migrations").glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
            print("applied", path.name)
        if "--seed" in argv:
            with conn.transaction():
                conn.execute((HERE / "seed.sql").read_text(encoding="utf-8"))
            print("seed applied")
    print("done")


if __name__ == "__main__":
    main(sys.argv[1:])
