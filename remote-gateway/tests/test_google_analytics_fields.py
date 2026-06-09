"""
Validate that the google-analytics field schema YAML is well-formed.

Run with:
    pytest remote-gateway/tests/test_google_analytics_fields.py -v
"""
from pathlib import Path

import pytest
import yaml

FIELDS_FILE = Path(__file__).parent.parent / "context" / "fields" / "google-analytics.yaml"

REQUIRED_FIELDS = [
    "date",
    "sessions",
    "users",
    "activeUsers",
    "newUsers",
    "pageviews",
    "bounceRate",
    "averageSessionDuration",
    "eventCount",
]

REQUIRED_FIELD_KEYS = {"display_name", "description", "type", "notes", "nullable"}


def _load_schema() -> dict:
    if not FIELDS_FILE.exists():
        pytest.fail(f"Field schema not found: {FIELDS_FILE}")
    return yaml.safe_load(FIELDS_FILE.read_text())


def test_schema_has_correct_integration_name():
    schema = _load_schema()
    assert schema.get("integration") == "google-analytics", (
        f"Expected integration 'google-analytics', got: {schema.get('integration')}"
    )


def test_schema_has_fields_key():
    schema = _load_schema()
    assert "fields" in schema, "Expected top-level 'fields' key in YAML."


def test_schema_contains_required_fields():
    schema = _load_schema()
    fields = schema.get("fields", {})
    for field in REQUIRED_FIELDS:
        assert field in fields, f"Expected field '{field}' in google-analytics schema."


def test_each_field_has_required_keys():
    schema = _load_schema()
    for field_name, field_def in schema.get("fields", {}).items():
        missing = REQUIRED_FIELD_KEYS - set(field_def.keys())
        assert not missing, (
            f"Field '{field_name}' is missing keys: {missing}"
        )
