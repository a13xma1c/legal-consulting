"""Alembic migrations must build the same schema as the models."""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask import Flask
from flask_migrate import upgrade
from sqlalchemy import inspect

from app import create_app
from app.extensions import db
from config import TestingConfig


@pytest.fixture()
def migrated_app(tmp_path: Path) -> Flask:
    """An app whose (file-backed) database was built purely from migrations."""

    class MigrationConfig(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'migrated.db'}"
        TESTING = False  # so create_app does not call create_all()
        WTF_CSRF_ENABLED = False

    application: Flask = create_app(MigrationConfig)
    with application.app_context():
        upgrade()
    return application


def test_upgrade_creates_all_tables(migrated_app: Flask) -> None:
    with migrated_app.app_context():
        tables = set(inspect(db.engine).get_table_names())
    expected = set(db.metadata.tables) | {"alembic_version"}
    assert expected <= tables


def test_migrations_match_models(migrated_app: Flask) -> None:
    """Fails when a model changes without a corresponding migration."""
    with migrated_app.app_context():
        with db.engine.connect() as connection:
            context = MigrationContext.configure(
                connection, opts={"compare_type": True, "render_as_batch": True}
            )
            diff = compare_metadata(context, db.metadata)
    assert diff == [], f"Models and migrations differ: {diff}"


def test_migrated_database_is_usable(migrated_app: Flask) -> None:
    with migrated_app.app_context():
        from app.cli import seed_database  # pylint: disable=import-outside-toplevel

        assert seed_database() is True
    client = migrated_app.test_client()
    assert client.get("/blog/").status_code == 200
    assert client.get("/forum/").status_code == 200
