"""为新部署生成本地配置；已有配置绝不覆盖。"""
import base64
import os
import secrets
from pathlib import Path


def initialize(path: Path) -> None:
    password = secrets.token_urlsafe(32)
    root_password = secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(32)
    browser_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    content = (
        "MYSQL_DATABASE=account_tasks\nMYSQL_USER=platform\n"
        f"MYSQL_PASSWORD={password}\nMYSQL_ROOT_PASSWORD={root_password}\n"
        f"DATABASE_URL=mysql+asyncmy://platform:{password}@127.0.0.1:3306/account_tasks\n"
        f"DOCKER_DATABASE_URL=mysql+asyncmy://platform:{password}@mysql:3306/account_tasks\n"
        f"ADMIN_ACCESS_TOKEN={access_token}\n"
        f"BROWSER_STORAGE_KEY={browser_key}\n"
        "REDIS_URL=redis://127.0.0.1:6379/0\nDEPENDENCY_TIMEOUT_SECONDS=3\n"
        "ENVIRONMENT=development\nONEBOT_HTTP_URL=\nONEBOT_WS_URL=\n"
        "ONEBOT_ACCESS_TOKEN=\nONEBOT_TIMEOUT_SECONDS=5\nONEBOT_RETRIES=1\n"
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / ".env"
    if target.exists():
        print(".env 已存在，保留现有配置。")
    else:
        initialize(target)
        print("已生成 .env，凭据未输出。")
