# Spec: Attio Field Documentation & Pre-flight Validation

**Date:** 2026-04-16  
**Status:** Approved  
**Scope:** `attio-people.yaml`, `remote-gateway/tools/attio.py`, `remote-gateway/tests/test_attio_tools.py`

---

## Problem

Agents calling `attio__create_record` receive cryptic 400 errors from the Attio API because they pass incorrect field names (e.g. `linkedin_url` instead of `linkedin`) or wrong value formats. The field registry YAML exists but only documents field semantics — it does not tell an agent how to write a field, which fields are writable, or which are required by the API. Agents guess and fail silently.

---

## Goals

1. Make `attio-people.yaml` the authoritative write reference for agents — field names, value formats, writability, and API-required status all live there.
2. Prevent 400 errors at the tool layer by validating field names against the YAML before making any HTTP call to Attio.
3. Return actionable error messages when validation fails so agents can self-correct.
4. Add test coverage for the validation logic and people-specific write formats.

## Non-goals

- Validation for proxied npm Attio tools (update_record, etc.) — the enriched YAML is sufficient prevention for those paths.
- Attio companies YAML enrichment — this spec establishes the pattern; companies follows in a separate task.
- Tool visibility / permissions management — separate spec.

---

## Design

### 1. YAML Schema: Three New Properties per Field

Every field in `attio-people.yaml` gains:

| Property | Type | Description |
|---|---|---|
| `writable` | bool | True if the field can be set via the Attio API. False for enrichment and computed fields. |
| `required_for_create` | bool | True if the Attio API will reject a POST /records without this field. |
| `write_format` | string or null | Exact JSON array string showing the value format for this field. Null for read-only fields. |

Example:

```yaml
  linkedin:
    display_name: "LinkedIn"
    description: "LinkedIn profile URL for this person."
    type: "string"
    notes: "Writable. Often auto-populated by enrichment."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"value": "https://linkedin.com/in/handle"}]'

  name:
    display_name: "Name"
    description: "Full name of the person (first + last)."
    type: "string"
    notes: "Attio personal-name type — stores first/last separately."
    nullable: true
    writable: true
    required_for_create: false
    write_format: '[{"first_name": "Jane", "last_name": "Doe", "full_name": "Jane Doe"}]'

  avatar_url:
    display_name: "Avatar URL"
    description: "URL of the person's profile photo, auto-populated by Attio enrichment."
    type: "string"
    notes: "Read-only. Set by Attio enrichment, not manually."
    nullable: true
    writable: false
    required_for_create: false
    write_format: null
```

All read-only fields (enrichment data, computed timestamps, interaction history, connection strength) get `writable: false` and `write_format: null`.

**Write formats by field type:**

| Attio type | write_format pattern |
|---|---|
| Simple string (job_title, linkedin, etc.) | `[{"value": "<string>"}]` |
| Personal name | `[{"first_name": "...", "last_name": "...", "full_name": "..."}]` |
| Email address | `[{"email_address": "user@example.com"}]` |
| Phone number | `[{"phone_number": "+1-555-555-5555"}]` |
| Record reference (company) | `[{"target_object": "companies", "target_record_id": "<id>"}]` |
| URL fields (angellist, facebook, etc.) | `[{"value": "https://..."}]` |

### 2. Pre-flight Validation in `attio__create_record`

Before making any HTTP call, `attio__create_record` validates the `values` dict:

```python
from core.field_registry import registry

def attio__create_record(object_type, values, ctx=None):
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

    # Proceed with HTTP call
    url = f"{_ATTIO_BASE}/objects/{object_type}/records"
    body = {"data": {"values": values}}
    ...
```

**Behavior:**
- If YAML exists for the object type: unknown field names and non-writable fields are caught before the HTTP call.
- If YAML does not exist (e.g. a new object type): validation is skipped gracefully — no false positives.
- The error response names the invalid fields and points to `get_field_definitions` for self-correction.
- `writable` defaults to `True` if the property is absent, preserving compatibility with existing YAML files that predate this change.

**Integration slug mapping:**

| `object_type` argument | Registry integration slug |
|---|---|
| `"people"` | `"attio-people"` |
| `"companies"` | `"attio-companies"` |

### 3. Docstring Fix

The `attio__create_record` docstring is updated to:
- Replace the `linkedin_url` example with `linkedin`
- Show correct `write_format` examples for all common people fields (name, email_addresses, job_title, linkedin, company)
- Add a note directing agents to call `get_field_definitions("attio-people")` for the full reference

### 4. Test Coverage

New test cases in `test_attio_tools.py`, using a temporary YAML fixture (not the live `attio-people.yaml`) so tests are self-contained:

| Test | What it verifies |
|---|---|
| `test_create_record_rejects_unknown_field` | Passing `linkedin_url` returns a structured error naming the invalid field and listing valid writable fields — no HTTP call is made |
| `test_create_record_rejects_readonly_field` | Passing `avatar_url` (writable: false) is also caught by pre-flight |
| `test_create_record_valid_people_payload` | A valid payload (`name`, `email_addresses`, `linkedin`, `job_title`) passes pre-flight and reaches the HTTP mock |
| `test_create_record_skips_validation_when_no_yaml` | When no YAML exists for the object type, the tool proceeds without error (graceful degradation) |

---

## Files Changed

| File | Change |
|---|---|
| `remote-gateway/context/fields/attio-people.yaml` | Add `writable`, `required_for_create`, `write_format` to all fields |
| `remote-gateway/tools/attio.py` | Add pre-flight validation; fix docstring (`linkedin_url` → `linkedin`) |
| `remote-gateway/tests/test_attio_tools.py` | Add 4 new test cases for validation logic |

---

## Out of Scope / Future Work

- `attio-companies.yaml` enrichment (same pattern, follow-on task)
- Pre-flight validation for `attio__search_records` (no write risk)
- Extending validation to proxied npm tools (update_record, etc.)
- Tool visibility / permissions management (separate spec)
