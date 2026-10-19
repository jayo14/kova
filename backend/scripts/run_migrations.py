#!/usr/bin/env python3
"""Run and verify database migrations using Alembic's programmatic API."""

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def main() -> int:
    parser = argparse.ArgumentParser(description="Alembic migration runner and verifier")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only display current migration status without applying upgrades",
    )
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parent.parent
    ini_path = backend_dir / "alembic.ini"

    if not ini_path.exists():
        print(f"Error: alembic.ini not found at {ini_path}", file=sys.stderr)
        return 1

    alembic_cfg = Config(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    print(f"Checking database migration status ({ini_path})...")
    command.current(alembic_cfg)

    if args.check_only:
        return 0

    print("Applying migrations up to head...")
    command.upgrade(alembic_cfg, "head")
    print("Migrations applied successfully. Current status:")
    command.current(alembic_cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
