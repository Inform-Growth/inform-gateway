"""Shared pytest fixtures for the remote-gateway test suite.

Provides a function-scoped ``store`` fixture backed by a real PostgreSQL
instance (via pytest-postgresql). Each test gets an isolated database.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pytest_postgresql import factories

sys.path.insert(0, str(Path(__file__).parent.parent / "core"))

from telemetry import TelemetryStore

postgresql_proc = factories.postgresql_proc()
postgresql = factories.postgresql("postgresql_proc")


@pytest.fixture()
def store(postgresql):
    """Function-scoped TelemetryStore backed by a fresh Postgres database."""
    params = postgresql.get_dsn_parameters()
    dsn = " ".join(f"{k}={v}" for k, v in params.items() if v)
    return TelemetryStore(dsn=dsn)
