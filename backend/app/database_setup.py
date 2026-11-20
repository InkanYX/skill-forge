"""Local setup commands; credentials stay in memory and the ignored .env file."""

import argparse
import json
import subprocess

import psycopg
from psycopg import sql
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url

from app.database import BACKEND_DIR, database_url, data_directory, import_file_configs, make_engine, storage_status


def bootstrap(container: str):
    if database_url():
        print("已有 DATABASE_URL，保留原配置。")
        return
    inspected = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, check=True)
    info = json.loads(inspected.stdout)[0]
    values = dict(item.split("=", 1) for item in info["Config"].get("Env", []) if "=" in item)
    user = values.get("POSTGRES_USER", "postgres")
    password = values.get("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("容器未提供可直接读取的密码，请自行配置 backend/.env。")
    bindings = info["NetworkSettings"]["Ports"].get("5432/tcp") or []
    binding = next((item for item in bindings if item["HostIp"] == "127.0.0.1"), None)
    if not binding:
        raise RuntimeError("未找到仅绑定本机的 PostgreSQL 端口，请检查容器配置。")
    options = dict(host="127.0.0.1", port=int(binding["HostPort"]), user=user, password=password, connect_timeout=5)
    with psycopg.connect(dbname=values.get("POSTGRES_DB", user), autocommit=True, **options) as connection:
        exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("skill_forge",)).fetchone()
        if not exists:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier("skill_forge")))
    url = URL.create("postgresql+psycopg", username=user, password=password, host="127.0.0.1", port=options["port"], database="skill_forge")
    path = BACKEND_DIR / ".env"
    # Exclusive creation prevents overwriting unrelated local settings.
    with path.open("x", encoding="utf-8") as handle:
        handle.write("DATABASE_URL=" + json.dumps(url.render_as_string(hide_password=False)) + "\n")
    path.chmod(0o600)
    print("已准备独立数据库 skill_forge，并将连接信息写入忽略的 backend/.env（不显示密码）。")


def migrate(url: str):
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")


def main():
    parser = argparse.ArgumentParser(description="Skill Forge 本机数据库准备")
    parser.add_argument("action", choices=["bootstrap", "migrate", "check"])
    parser.add_argument("--container", default="postgres")
    args = parser.parse_args()
    engine = None
    try:
        if args.action == "bootstrap":
            bootstrap(args.container)
        url = database_url()
        if not url:
            raise RuntimeError("尚未配置 DATABASE_URL。")
        if not make_url(url).drivername.startswith("postgresql"):
            raise RuntimeError("此命令只用于 PostgreSQL。")
        if args.action in ("bootstrap", "migrate"):
            migrate(url)
        engine = make_engine(url)
        if args.action in ("bootstrap", "migrate"):
            count = import_file_configs(data_directory(), engine)
            print(f"表结构迁移完成，导入 {count} 项文件配置；原 JSON 和加密文件均保留。")
        status = storage_status(engine)
        print(json.dumps(status, ensure_ascii=False))
        if status["status"] != "ready":
            raise RuntimeError("数据库尚未就绪。")
    except Exception as error:
        # Never print database URLs, container environment, SQL parameters or keys.
        print(f"数据库准备未完成（{type(error).__name__}）。请检查连接、容器状态与本机加密文件。")
        raise SystemExit(1) from None
    finally:
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
