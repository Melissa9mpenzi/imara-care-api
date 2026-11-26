from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.database import Base


def migration_config(connection) -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.attributes["connection"] = connection
    return config


def test_initial_migration_creates_all_model_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "head")

        assert set(Base.metadata.tables).issubset(
            set(inspect(engine).get_table_names())
        )
    finally:
        engine.dispose()


def test_initial_migration_refuses_unrecognized_existing_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unexpected.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

        with engine.begin() as connection:
            with pytest.raises(RuntimeError, match="unexpected tables"):
                command.upgrade(migration_config(connection), "head")

        tables = set(inspect(engine).get_table_names())
        assert "unrelated" in tables
        assert "facilities" not in tables
    finally:
        engine.dispose()
