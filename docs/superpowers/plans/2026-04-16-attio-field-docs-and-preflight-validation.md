# Attio Field Docs & Pre-flight Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich `attio-people.yaml` with write metadata and add field-name validation to `attio__create_record` so agents receive actionable errors instead of 400s from Attio.

**Architecture:** `attio__create_record` imports the module-level `FieldRegistry` singleton and validates field names before making any HTTP call. The YAML gains three new per-field properties (`writable`, `required_for_create`, `write_format`) that serve as the authoritative reference for agents. Tests use a temp YAML fixture and monkeypatching to stay self-contained.

**Tech Stack:** Python 3.11+, httpx, pyyaml, pytest, `remote-gateway/core/field_registry.py` (FieldRegistry), `remote-gateway/context/fields/attio-people.yaml`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `remote-gateway/tests/test_attio_tools.py` | Modify | Add 4 new test cases for pre-flight validation |
| `remote-gateway/tools/attio.py` | Modify | Import registry, add pre-flight validation block, fix docstring |
| `remote-gateway/context/fields/attio-people.yaml` | Modify | Add `writable`, `required_for_create`, `write_format` to every field |

---

## Task 1: Write Failing Tests (TDD)

**Files:**
- Modify: `remote-gateway/tests/test_attio_tools.py`

- [ ] **Step 1.1: Add imports and YAML fixture helper at the top of the test file**

Open `remote-gateway/tests/test_attio_tools.py`. After the existing imports block, add:

```python
import textwrap
from pathlib import Path

from core.field_registry import FieldRegistry


# ---------------------------------------------------------------------------
# Helpers for pre-flight validation tests
# ---------------------------------------------------------------------------

_PEOPLE_YAML = textwrap.dedent("""\
    integration: "attio"
    object: "people"
    fields:
      name:
        display_name: "Name"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]'
      email_addresses:
        display_name: "Email Addresses"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"email_address": "jane@acme.com"}]'
      linkedin:
        display_name: "LinkedIn"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"value": "https://linkedin.com/in/handle"}]'
      job_title:
        display_name: "Job Title"
        type: "string"
        nullable: true
        writable: true
        required_for_create: false
        write_format: '[{"value": "Head of Sales"}]'
      avatar_url:
        display_name: "Avatar URL"
        type: "string"
        nullable: true
        writable: false
        required_for_create: false
        write_format: null
""")


def _make_test_registry(tmp_path: Path) -> FieldRegistry:
    """Write minimal YAML fixtures and return a FieldRegistry pointed at tmp_path."""
    (tmp_path / "attio-people.yaml").write_text(_PEOPLE_YAML)
    return FieldRegistry(fields_dir=tmp_path)
```

- [ ] **Step 1.2: Add four new test cases at the bottom of the file**

Append after the last existing test:

```python
# ---------------------------------------------------------------------------
# attio__create_record — pre-flight validation
# ---------------------------------------------------------------------------


def test_create_record_rejects_unknown_field(monkeypatch, tmp_path):
    """create_record returns a structured error when an unknown field is passed."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path))

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record(
            "people",
            {"linkedin_url": [{"value": "https://linkedin.com/in/test"}]},
        )

    assert "error" in result
    assert "linkedin_url" in result["error"]
    assert "linkedin" in result["valid_writable_fields"]
    # No HTTP call should have been made
    mock_client.post.assert_not_called()


def test_create_record_rejects_readonly_field(monkeypatch, tmp_path):
    """create_record returns a structured error when a read-only field is passed."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path))

    mock_client = _mock_client(
        post_responses=[_mock_response({"data": {"id": {"record_id": "r"}, "values": {}}})]
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record(
            "people",
            {"avatar_url": [{"value": "https://example.com/photo.jpg"}]},
        )

    assert "error" in result
    assert "avatar_url" in result["error"]
    assert "avatar_url" not in result["valid_writable_fields"]
    mock_client.post.assert_not_called()


def test_create_record_valid_people_payload(monkeypatch, tmp_path):
    """create_record passes pre-flight and makes the HTTP call for a valid payload."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    monkeypatch.setattr(attio_module, "registry", _make_test_registry(tmp_path))

    mock_client = _mock_client(
        post_responses=[
            _mock_response({"data": {"id": {"record_id": "rec-valid-123"}, "values": {}}})
        ]
    )

    values = {
        "name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}],
        "email_addresses": [{"email_address": "jane@acme.com"}],
        "linkedin": [{"value": "https://linkedin.com/in/janedoe"}],
        "job_title": [{"value": "Head of Sales"}],
    }

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record("people", values)

    assert result["record_id"] == "rec-valid-123"
    mock_client.post.assert_called_once()


def test_create_record_skips_validation_when_no_yaml(monkeypatch, tmp_path):
    """create_record skips validation gracefully when no YAML exists for the object type."""
    monkeypatch.setenv("ATTIO_API_KEY", "test-key")

    import tools.attio as attio_module
    # tmp_path has no YAML files — registry will return empty defs
    monkeypatch.setattr(attio_module, "registry", FieldRegistry(fields_dir=tmp_path))

    mock_client = _mock_client(
        post_responses=[
            _mock_response({"data": {"id": {"record_id": "rec-skip-456"}, "values": {}}})
        ]
    )

    with patch("httpx.Client", return_value=mock_client):
        result = attio_module.attio__create_record(
            "custom_object",
            {"some_unknown_field": [{"value": "x"}]},
        )

    # No error — validation was skipped, HTTP call was made
    assert "error" not in result
    assert result["record_id"] == "rec-skip-456"
```

- [ ] **Step 1.3: Run the new tests to confirm they fail**

```bash
cd /path/to/inform-gateway
pytest remote-gateway/tests/test_attio_tools.py -k "preflight or rejects or skips_validation or valid_people" -v
```

Expected: 4 failures — `AttributeError: module 'tools.attio' has no attribute 'registry'` (or similar). If you see a different error, read it carefully — the fixture or import path may need adjustment based on your local `sys.path`.

---

## Task 2: Add Pre-flight Validation to `attio__create_record`

**Files:**
- Modify: `remote-gateway/tools/attio.py`

- [ ] **Step 2.1: Add the registry import at the top of `attio.py`**

In `remote-gateway/tools/attio.py`, after the existing imports (`from __future__ import annotations`, `import os`, `from typing import Any`), add:

```python
from core.field_registry import registry
```

The full imports block should now read:

```python
from __future__ import annotations

import os
from typing import Any

from core.field_registry import registry
```

- [ ] **Step 2.2: Replace the `attio__create_record` function with the validated version**

Replace the entire `attio__create_record` function (lines 81–120 in the original file) with:

```python
def attio__create_record(
    object_type: str,
    values: dict[str, Any],
    ctx: Any | None = None,
) -> dict[str, Any]:
    """Create a new record in Attio.

    Creates a company or person record with the given attribute values using
    the Attio v2 records endpoint. Field names are validated against the field
    registry before any HTTP call is made — unknown or read-only fields return
    a structured error with the list of valid writable fields and a hint.

    Call get_field_definitions("attio-people") or get_field_definitions("attio-companies")
    to see all valid field names, their write_format examples, and which are required.

    Values format for people:
        {"name": [{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]}
        {"email_addresses": [{"email_address": "jane@acme.com"}]}
        {"job_title": [{"value": "Head of Sales"}]}
        {"linkedin": [{"value": "https://linkedin.com/in/janedoe"}]}
        {"phone_numbers": [{"phone_number": "+1-555-555-5555"}]}

    Values format for companies:
        {"name": [{"value": "Acme Inc"}], "domains": [{"domain": "acme.io"}]}

    Company reference fields require target_object alongside target_record_id:
        {"company": [{"target_object": "companies", "target_record_id": "<id>"}]}

    Args:
        object_type: Record type to create — "companies" or "people".
        values: Attribute values in Attio REST API format (see docstring examples).
        ctx: MCP Context for session state (optional).

    Returns:
        Dict with 'record_id', 'object_type', and 'data' (the created record).
        On validation failure, returns 'error', 'valid_writable_fields', and 'hint'.
    """
    import httpx

    # Pre-flight: validate field names against the registry
    integration = f"attio-{object_type}"
    field_defs = registry.get_all(integration)

    if field_defs:
        writable_fields = {k for k, v in field_defs.items() if v.get("writable", True)}
        invalid = [k for k in values if k not in writable_fields]

        if invalid:
            return {
                "error": f"Invalid or read-only field(s) for {object_type}: {invalid}",
                "valid_writable_fields": sorted(writable_fields),
                "hint": (
                    f"Call get_field_definitions('{integration}') to see correct field "
                    "names and write_format examples."
                ),
            }

    url = f"{_ATTIO_BASE}/objects/{object_type}/records"
    body: dict[str, Any] = {"data": {"values": values}}

    with httpx.Client() as client:
        resp = client.post(url, headers=_headers(), json=body)

    resp.raise_for_status()
    result = resp.json()
    record = result.get("data", {})
    record_id = record.get("id", {}).get("record_id", "")
    return {"record_id": record_id, "object_type": object_type, "data": record}
```

- [ ] **Step 2.3: Run the four new tests — they should now pass**

```bash
pytest remote-gateway/tests/test_attio_tools.py -k "preflight or rejects or skips_validation or valid_people" -v
```

Expected output:
```
test_attio_tools.py::test_create_record_rejects_unknown_field PASSED
test_attio_tools.py::test_create_record_rejects_readonly_field PASSED
test_attio_tools.py::test_create_record_valid_people_payload PASSED
test_attio_tools.py::test_create_record_skips_validation_when_no_yaml PASSED
```

- [ ] **Step 2.4: Run the full test suite to confirm no regressions**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v
```

Expected: all tests pass. If an existing test fails, check whether it imports `attio__create_record` directly or via the module — the monkeypatching only works via the module reference (`attio_module.registry`).

- [ ] **Step 2.5: Commit**

```bash
git add remote-gateway/tools/attio.py remote-gateway/tests/test_attio_tools.py
git commit -m "feat: add pre-flight field validation to attio__create_record

Validates field names against the YAML registry before making any HTTP
call. Unknown or read-only fields return a structured error with the list
of valid writable fields. Gracefully skips validation when no YAML exists
for the object type.

Also fixes docstring: linkedin_url example replaced with linkedin."
```

---

## Task 3: Enrich `attio-people.yaml` with Write Metadata

**Files:**
- Modify: `remote-gateway/context/fields/attio-people.yaml`

- [ ] **Step 3.1: Replace the contents of `attio-people.yaml` with the enriched version**

Replace the full file with the following. Every field gains `writable`, `required_for_create`, and `write_format`. Read-only fields get `writable: false` and `write_format: null`.

```yaml
integration: "attio"
object: "people"
source_url: "https://developers.attio.com/reference/get_v2-objects-people-attributes"
discovered_at: "2026-04-03"
last_drift_check: "2026-04-16"

fields:
  record_id:
    display_name: "Record ID"
    description: "Unique identifier for this person record in Attio."
    type: "id"
    notes: "System-generated. Read-only. Use this to reference the person in API calls."
    nullable: false
    writable: false
    required_for_create: false
    write_format: null

  name:
    display_name: "Name"
    description: "Full name of the person (first + last)."
    type: "string"
    notes: "Attio personal-name type — stores first/last separately but returns combined. All three subfields (first_name, last_name, full_name) must be provided together."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]'

  email_addresses:
    display_name: "Email Addresses"
    description: "One or more email addresses for this person. First entry is the primary."
    type: "string"
    notes: "Multiselect. Unique across workspace — duplicate emails will be merged into an existing record."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"email_address": "jane@acme.com"}]'

  description:
    display_name: "Description"
    description: "Free-text bio or notes about this person."
    type: "string"
    notes: "Writable. Not shown by default in list views."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "Bio or background notes about this person."}]'

  company:
    display_name: "Company"
    description: "The company this person is affiliated with (links to companies object)."
    type: "id"
    notes: "Record reference → companies. Single value. Requires an existing Attio company record_id."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"target_object": "companies", "target_record_id": "<company_record_id>"}]'

  job_title:
    display_name: "Job Title"
    description: "The person's current job title or role."
    type: "string"
    notes: "Free-text. Writable."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "Head of Sales"}]'

  avatar_url:
    display_name: "Avatar URL"
    description: "URL of the person's profile photo, auto-populated by Attio enrichment."
    type: "string"
    notes: "Read-only. Set by Attio enrichment, not manually."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  phone_numbers:
    display_name: "Phone Numbers"
    description: "One or more phone numbers for this person."
    type: "string"
    notes: "Multiselect. Stores country code + number."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"phone_number": "+1-555-555-5555"}]'

  primary_location:
    display_name: "Primary Location"
    description: "Geographic location where this person is based."
    type: "string"
    notes: "Attio location type — includes city, state, country. All subfields are optional."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"locality": "San Francisco", "region": "CA", "country_code": "US"}]'

  angellist:
    display_name: "AngelList"
    description: "AngelList profile URL for this person."
    type: "string"
    notes: "Writable. Free-text URL."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://angel.co/u/handle"}]'

  facebook:
    display_name: "Facebook"
    description: "Facebook profile URL for this person."
    type: "string"
    notes: "Writable. Free-text URL."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://facebook.com/handle"}]'

  instagram:
    display_name: "Instagram"
    description: "Instagram profile URL for this person."
    type: "string"
    notes: "Writable. Free-text URL."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://instagram.com/handle"}]'

  linkedin:
    display_name: "LinkedIn"
    description: "LinkedIn profile URL for this person."
    type: "string"
    notes: "Writable. Often auto-populated by enrichment. Field name is 'linkedin', not 'linkedin_url'."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://linkedin.com/in/handle"}]'

  twitter:
    display_name: "Twitter"
    description: "Twitter/X profile URL or handle for this person."
    type: "string"
    notes: "Writable. Free-text."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://twitter.com/handle"}]'

  twitter_follower_count:
    display_name: "Twitter Follower Count"
    description: "Number of Twitter/X followers this person has."
    type: "number"
    notes: "Read-only. Auto-populated by Attio enrichment."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  first_calendar_interaction:
    display_name: "First Calendar Interaction"
    description: "Date and details of the first calendar event (meeting) with this person."
    type: "timestamp"
    notes: "Read-only. Computed from connected calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  last_calendar_interaction:
    display_name: "Last Calendar Interaction"
    description: "Date and details of the most recent calendar event with this person."
    type: "timestamp"
    notes: "Read-only. Computed from connected calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  next_calendar_interaction:
    display_name: "Next Calendar Interaction"
    description: "Date and details of the next upcoming calendar event with this person."
    type: "timestamp"
    notes: "Read-only. Computed from connected calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  first_email_interaction:
    display_name: "First Email Interaction"
    description: "Date of the first email exchange with this person."
    type: "timestamp"
    notes: "Read-only. Computed from connected email."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  last_email_interaction:
    display_name: "Last Email Interaction"
    description: "Date of the most recent email exchange with this person."
    type: "timestamp"
    notes: "Read-only. Computed from connected email."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  first_interaction:
    display_name: "First Interaction"
    description: "Date of the very first interaction with this person across all channels."
    type: "timestamp"
    notes: "Read-only. Aggregated across email and calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  last_interaction:
    display_name: "Last Interaction"
    description: "Date of the most recent interaction with this person across all channels."
    type: "timestamp"
    notes: "Read-only. Useful for relationship health checks."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  next_interaction:
    display_name: "Next Interaction"
    description: "Date of the next scheduled interaction with this person."
    type: "timestamp"
    notes: "Read-only. Derived from calendar."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  strongest_connection_strength:
    display_name: "Connection Strength"
    description: "How strong the team's relationship with this person is, based on interaction history."
    type: "string"
    notes: "Read-only enum: Very weak, Weak, Good, Strong, Very strong. Computed by Attio."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  strongest_connection_user:
    display_name: "Strongest Connection"
    description: "The workspace member who has the strongest relationship with this person."
    type: "id"
    notes: "Read-only. Actor reference to a workspace member."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  associated_deals:
    display_name: "Associated Deals"
    description: "Deals linked to this person."
    type: "id"
    notes: "Multiselect record reference → deals. Read-only on create; managed via deal records."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  associated_users:
    display_name: "Associated Users"
    description: "Product users linked to this person record."
    type: "id"
    notes: "Multiselect record reference → users object. Read-only on create."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null

  created_at:
    display_name: "Created At"
    description: "Timestamp when this person record was created in Attio."
    type: "timestamp"
    notes: "Read-only. UTC."
    nullable: false
    writable: false
    required_for_create: false
    write_format: null

  created_by:
    display_name: "Created By"
    description: "The workspace member or system that created this person record."
    type: "id"
    notes: "Read-only. Actor reference."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null
```

- [ ] **Step 3.2: Run lint check**

```bash
cd /path/to/inform-gateway
ruff check remote-gateway/tools/attio.py remote-gateway/tests/test_attio_tools.py
```

Expected: no errors. If ruff flags anything, fix it before continuing.

- [ ] **Step 3.3: Run the full test suite one final time**

```bash
pytest remote-gateway/tests/test_attio_tools.py -v
```

Expected: all tests pass, including the 4 new pre-flight validation tests.

- [ ] **Step 3.4: Commit**

```bash
git add remote-gateway/context/fields/attio-people.yaml
git commit -m "docs: enrich attio-people.yaml with writable/required_for_create/write_format

Adds three new properties to every field so agents can call
get_field_definitions('attio-people') to get correct field names,
value formats, and writability before constructing a create payload.

Fixes linkedin field note: clarifies field name is 'linkedin', not 'linkedin_url'."
```

---

## Self-Review Checklist (run before marking complete)

- **Spec coverage:**
  - [x] YAML gains `writable`, `required_for_create`, `write_format` → Task 3
  - [x] Pre-flight validation in `attio__create_record` → Task 2
  - [x] Docstring fix `linkedin_url` → `linkedin` → Task 2, Step 2.2
  - [x] `test_create_record_rejects_unknown_field` → Task 1, Step 1.2
  - [x] `test_create_record_rejects_readonly_field` → Task 1, Step 1.2
  - [x] `test_create_record_valid_people_payload` → Task 1, Step 1.2
  - [x] `test_create_record_skips_validation_when_no_yaml` → Task 1, Step 1.2
  - [x] Graceful degradation when no YAML → validation block gated on `if field_defs`
  - [x] `writable` defaults to `True` if property absent → `v.get("writable", True)` in Task 2

- **Type consistency:** `registry.get_all(integration)` returns `dict[str, Any]` per `field_registry.py:111`. `writable_fields` is a set of strings. `invalid` is a list of strings. All consistent across tasks.

- **No placeholders:** All steps contain exact code, exact commands, and exact expected output.
