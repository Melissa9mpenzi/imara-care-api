from pathlib import Path

from alembic import command
from alembic.config import Config

from app.main import initialize_database


def bootstrap_database() -> None:
    project_root = Path(__file__).resolve().parents[1]
    migration_config = Config(str(project_root / "alembic.ini"))
    migration_config.set_main_option("script_location", str(project_root / "migrations"))
    command.upgrade(migration_config, "head")
    initialize_database()


if __name__ == "__main__":
    bootstrap_database()
