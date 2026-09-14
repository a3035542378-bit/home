import os
import subprocess
from pathlib import Path


def test_migration_upgrade_downgrade(tmp_path):
    import sys
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"}
    for args in [("upgrade", "head"), ("check",), ("downgrade", "733e680fde79"),
                 ("upgrade", "head"), ("check",), ("downgrade", "base"), ("upgrade", "head")]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), *args],
            env=env, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
