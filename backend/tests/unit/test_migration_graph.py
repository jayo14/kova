from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_budget_migration_is_latest_and_follows_versioned_credential_migration():
    backend_dir = Path(__file__).parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_current_head() == "034_add_exploration_budget_fields"
    assert scripts.get_revision("034_add_exploration_budget_fields").down_revision == "033"
