# Attio Integration — Field & Payload Notes

**Source:** Attio CRM via remote gateway MCP tools
**Last updated:** 2026-04-04
**Workspace:** inform-growth

---

## Tool Payload Reference

### `upsert-record`
Creates or updates a record. Matches on `matching_attribute` — if found, updates; if not, creates.

```json
{
  "object": "people",
  "matching_attribute": "email_addresses",
  "values": {
    "email_addresses": [{ "email_address": "name@example.com" }],
    "name": {
      "full_name": "First Last",
      "first_name": "First",
      "last_name": "Last"
    },
    "job_title": "VP of Sales"
  }
}
```

**Quirks:**
- Top-level params are `object` and `values` — NOT `object_type` and `attributes`. Using the wrong names throws a validation error with no helpful message.
- `name` field type is `personal-name`. Requires `full_name` (string) to be present. Providing only `first_name` + `last_name` without `full_name` throws: `"Required: full_name"`.
- `company` field is a `record-reference` to the `companies` object. You cannot set it to a company name string. You must first upsert a company record and capture its `record_id`, then reference it.
- `email_addresses` is a multiselect — pass as array of `{ "email_address": "..." }` objects.
- Returns the full record with all attribute values on success.

**People object attribute slugs:**
| Slug | Type | Notes |
|---|---|---|
| `email_addresses` | email-address (multiselect) | Primary matching attribute. Array of `{email_address}`. |
| `name` | personal-name | Requires `full_name`. Optionally `first_name`, `last_name`. |
| `job_title` | text | Plain string |
| `company` | record-reference → companies | Needs Attio company `record_id`, not a name string |
| `phone_numbers` | phone-number (multiselect) | Array of phone objects |
| `primary_location` | location | Location object |
| `description` | text | Free text notes field |

---

### `add-record-to-list`
Adds an existing record to a list as a new list entry.

```json
{
  "list": "api_slug_or_list_id",
  "parent_object": "people",
  "parent_record_id": "<attio_record_id>"
}
```

**Quirks:**
- Params are `list`, `parent_object`, `parent_record_id` — NOT `list_id` and `record_id`. Using the wrong names throws a validation error.
- `list` accepts either the list's `api_slug` (e.g. `"revops_ai_infra_apr_2026"`) or the UUID. Prefer slug for readability.
- Duplicate entries are prevented by default. If the record already exists in the list, the existing entry ID is returned (no error).
- Returns `entry_id` on success.

---

### `create-task`
Creates a task, optionally linked to a record.

```json
{
  "content": "Task description text",
  "linked_record_object": "people",
  "linked_record_id": "<attio_record_id>"
}
```

**Quirks:**
- Linking params are `linked_record_object` and `linked_record_id` — NOT `linked_object` and `record_id`. Using the wrong names throws: `"linked_record_object and linked_record_id must both be provided or both be omitted"`.
- `content` is the task body — supports plain text. No markdown rendering confirmed.
- Returns `task_id` on success.
- Optional params: `deadline` (ISO 8601 datetime), `assignee_workspace_member_id`.

---

### `list-lists`
Returns all lists in the workspace.

```json
{}
```

**Key response fields per list:**
| Field | Notes |
|---|---|
| `list_id` | UUID — can be used as `list` param in `add-record-to-list` |
| `api_slug` | Kebab-style slug — also valid as `list` param, more readable |
| `parent_objects` | Object types the list is scoped to (e.g. `["people"]`) |

**Note:** Lists cannot be created via API. Users must create lists manually in the Attio UI before the agent can populate them. The API slug is auto-generated from the list name.

---

### `list-attribute-definitions`
Returns all attribute definitions for an object. Use to discover slugs before upserting.

```json
{ "object": "people" }
```

Returns paginated list of `{attribute_id, title, api_slug, type, is_writable, is_multiselect, is_unique}`.

---

## Workflow Pattern: Load Contacts to Campaign List

```
1. list-lists → find or confirm target list api_slug

2. For each contact:
   a. upsert-record(object="people", matching_attribute="email_addresses", values={...})
      → capture record_id from response
   b. add-record-to-list(list=api_slug, parent_object="people", parent_record_id=record_id)
   c. create-task(content="...", linked_record_object="people", linked_record_id=record_id)

3. Optionally: upsert company records first if you need the company linkage on people records
```

---

## Known Limitations
- **Cannot create lists via API** — must be created manually in Attio UI
- **`company` on people requires a record-reference** — plain string company names are not accepted
- **No bulk add to list** — must call `add-record-to-list` individually per record
