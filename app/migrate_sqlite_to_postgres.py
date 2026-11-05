import argparse
from itertools import islice
from pathlib import Path

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import URL

from app import models as _models
from app.config import settings
from app.database import Base


def migrate(source_path: Path, target_url: str) -> dict[str, int]:
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database not found: {source_path}")

    source_engine = create_engine(
        URL.create("sqlite", database=str(source_path.resolve()))
    )
    target_engine = create_engine(target_url, pool_pre_ping=True)

    try:
        if target_engine.dialect.name != "postgresql":
            raise ValueError("DATABASE_URL must point to a PostgreSQL database.")

        copied: dict[str, int] = {}
        with source_engine.connect() as source, target_engine.begin() as target:
            expected_tables = Base.metadata.sorted_tables
            source_tables = set(inspect(source).get_table_names())
            missing_tables = [
                table.name for table in expected_tables if table.name not in source_tables
            ]
            if missing_tables:
                raise ValueError(
                    "The SQLite database is missing expected clinical tables: "
                    + ", ".join(missing_tables)
                )

            existing_target_tables = inspect(target).get_table_names()
            if existing_target_tables:
                raise ValueError(
                    "The PostgreSQL database must be empty before migration. "
                    "Found tables: " + ", ".join(existing_target_tables)
                )

            Base.metadata.create_all(bind=target)
            for table in expected_tables:
                rows = source.execute(select(table)).mappings()
                copied[table.name] = 0
                while batch := list(islice(rows, 500)):
                    target.execute(table.insert(), [dict(row) for row in batch])
                    copied[table.name] += len(batch)

        return copied
    finally:
        source_engine.dispose()
        target_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy the clinical SQLite database into an empty PostgreSQL database."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "imara-care.db",
        help="Path to the existing SQLite database (defaults to backend/imara-care.db).",
    )
    args = parser.parse_args()

    copied = migrate(args.source, settings.database_url)
    print("Clinical records copied to PostgreSQL:")
    for table, count in copied.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
