import os
import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Base, DatabaseConfigStore, ModelConfiguration, database_url, import_file_configs, make_engine, storage_status
from app.database_setup import migrate
from app.main import create_app
from app.model_configs import ConfigInput, FileConfigStore

KEY = "unit-test-database-secret-not-real"
VALUES = {"name": "数据库接口", "base_url": "https://api.example.com/v1", "model_name": "test-model", "api_key": KEY}


@pytest.fixture
def db(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_database_store_preserves_cipher_and_can_reopen(tmp_path, db):
    store = DatabaseConfigStore(tmp_path / "data", db)
    item = store.save(ConfigInput(**VALUES))
    assert item.has_api_key
    assert KEY not in item.model_dump_json()
    with Session(db) as session:
        encrypted = session.get(ModelConfiguration, item.id).encrypted_key
        assert KEY not in encrypted
    reopened = DatabaseConfigStore(tmp_path / "data", db)
    assert reopened.resolve_key(item.id, ConfigInput(**{**VALUES, "api_key": None})) == KEY
    updated = reopened.save(ConfigInput(**{**VALUES, "name": "修改后", "api_key": None}), item.id)
    assert updated.name == "修改后"
    assert len(reopened.list()) == 1
    assert not store.path.exists()


def test_import_is_repeatable_and_keeps_original_files(tmp_path, db):
    legacy = FileConfigStore(tmp_path)
    item = legacy.save(ConfigInput(**VALUES))
    original = legacy.path.read_bytes()
    assert import_file_configs(tmp_path, db) == 1
    assert import_file_configs(tmp_path, db) == 0
    assert legacy.path.read_bytes() == original
    assert DatabaseConfigStore(tmp_path, db).resolve_key(item.id, ConfigInput(**{**VALUES, "api_key": None})) == KEY


def test_import_conflict_does_not_overwrite_database(tmp_path, db):
    legacy = FileConfigStore(tmp_path)
    item = legacy.save(ConfigInput(**VALUES))
    import_file_configs(tmp_path, db)
    store = DatabaseConfigStore(tmp_path, db)
    store.save(ConfigInput(**{**VALUES, "name": "数据库新版本"}), item.id)
    with pytest.raises(ValueError):
        import_file_configs(tmp_path, db)
    assert store.list()[0].name == "数据库新版本"


def test_missing_key_with_database_records_is_not_regenerated(tmp_path, db):
    store = DatabaseConfigStore(tmp_path, db)
    item = store.save(ConfigInput(**VALUES))
    store.key_path.unlink()
    with pytest.raises(HTTPException) as error:
        store.resolve_key(item.id, ConfigInput(**{**VALUES, "api_key": None}))
    assert error.value.status_code == 503
    assert not store.key_path.exists()


def test_unavailable_schema_reports_unready_without_secrets(tmp_path):
    url = f"sqlite:///{(tmp_path / 'uninitialized.db').as_posix()}"
    engine = make_engine(url)
    assert storage_status(engine)["status"] == "unavailable"
    with TestClient(create_app(tmp_path / "data", db_url=url)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/system/status").json()["status"] == "unavailable"
        result = client.get("/api/model-configs")
        assert result.status_code == 503
        assert "sqlalchemy" not in result.text.lower()
    engine.dispose()


def test_api_uses_database_without_changing_configuration_contract(tmp_path, db):
    with TestClient(create_app(tmp_path / "data", db_url=str(db.url))) as client:
        response = client.post("/api/model-configs", json=VALUES)
        assert response.status_code == 201
        assert KEY not in response.text
        assert client.get("/api/system/status").json()["status"] == "ready"
        assert len(client.get("/api/model-configs").json()) == 1
    with Session(db) as session:
        assert len(list(session.scalars(select(ModelConfiguration)))) == 1


def test_alembic_upgrade_is_repeatable(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrations.db').as_posix()}"
    migrate(url)
    migrate(url)
    engine = make_engine(url)
    assert storage_status(engine)["status"] == "ready"
    engine.dispose()


def test_multi_model_database_config_and_legacy_migration_keep_credentials(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from app.database import BACKEND_DIR
    url = f"sqlite:///{(tmp_path / 'legacy-model.db').as_posix()}"
    settings = Config(str(BACKEND_DIR / 'alembic.ini'))
    settings.attributes['database_url'] = url
    command.upgrade(settings, '0008_artwork_favorites')
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO model_configurations (id,name,base_url,model_name,encrypted_key,updated_at) VALUES ('legacy','legacy','https://api.example.com/v1','old-image','cipher-preserved','2026-01-01')"))
    migrate(url)
    with Session(engine) as session:
        legacy = session.get(ModelConfiguration, 'legacy')
        assert json.loads(legacy.model_names) == ['old-image'] and legacy.encrypted_key == 'cipher-preserved'
    store = DatabaseConfigStore(tmp_path / 'data', engine)
    # This fixture uses an opaque legacy ciphertext; remove only that synthetic
    # row before creating a separate correctly encrypted configuration.
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM model_configurations WHERE id = 'legacy'"))
    item = store.save(ConfigInput(**{**VALUES, 'model_names': ['test-model', 'second-model']}))
    updated = store.save(ConfigInput(**{**VALUES, 'api_key': None, 'model_name': 'second-model', 'model_names': ['test-model', 'second-model']}), item.id)
    assert updated.model_names == ['test-model', 'second-model'] and updated.model_name == 'second-model'
    assert DatabaseConfigStore(tmp_path / 'data', engine).resolve_key(item.id, ConfigInput(**{**VALUES, 'api_key': None})) == KEY
    engine.dispose()


@pytest.mark.skipif(os.environ.get("SKILL_FORGE_TEST_POSTGRES") != "1", reason="需要显式启用本机 PostgreSQL 集成测试")
def test_real_postgres_roundtrip_is_rolled_back(tmp_path):
    from sqlalchemy.engine import make_url
    url = database_url()
    assert url and make_url(url).database == "skill_forge"
    assert make_url(url).host in ("127.0.0.1", "localhost")
    engine = make_engine(url)
    identifier = None
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                # Isolate configuration/encryption tests from saved user keys.
                # Both this schema and its rows disappear on rollback.
                from uuid import uuid4
                schema = 'test_configs_' + uuid4().hex
                connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
                connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
                Base.metadata.create_all(connection)
                store = DatabaseConfigStore(tmp_path, connection)
                item = store.save(ConfigInput(**VALUES))
                identifier = item.id
                assert store.resolve_key(item.id, ConfigInput(**{**VALUES, "api_key": None})) == KEY
                with Session(engine) as other_session:
                    assert other_session.get(ModelConfiguration, identifier) is None
                updated = store.save(ConfigInput(**{**VALUES, "api_key": None, "name": "事务测试"}), item.id)
                assert updated.name == "事务测试"
            finally:
                transaction.rollback()
        with Session(engine) as session:
            assert session.get(ModelConfiguration, identifier) is None
    finally:
        engine.dispose()
