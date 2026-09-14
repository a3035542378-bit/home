import importlib.util
from pathlib import Path

import pytest
from dotenv import dotenv_values

from app.core.config import Settings


def test_configuration_generator(tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/init_env.py"
    spec = importlib.util.spec_from_file_location("init_env", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / ".env"
    module.initialize(target)
    original = target.read_text()
    assert target.stat().st_mode & 0o777 == 0o600
    config = Settings(_env_file=target)
    assert config.admin_access_token.get_secret_value()
    assert config.onebot_http_url is None
    assert dotenv_values(target)["MYSQL_PASSWORD"]
    with pytest.raises(FileExistsError):
        module.initialize(target)
    assert target.read_text() == original


def test_missing_database_configuration(monkeypatch):
    from pydantic import ValidationError
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
