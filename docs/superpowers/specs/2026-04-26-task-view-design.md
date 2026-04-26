# Task View — Design Spec

**Date:** 2026-04-26
**Status:** Approved

---

## Overview

Add a **Tasks** tab to the admin dashboard that shows a history of declared agent tasks, with inline drill-down into the associated tool call logs for each task.

---

## Goals

- Give operators visibility into what agents have been doing and whether tasks complete successfully.
- Enable cross-referencing task intent with raw tool call logs to diagnose failures.
- Keep the UI simple: lists of things, no charts or aggregations.

---

## Layout

### Tab placement

Insert a new **Tasks** tab in the tab bar between **Logs** and **Org Profile**.

### Two-column split

Reuse the same `ops-grid` / `section-box` two-column layout used by the Users/Permissions panel.

**Left panel — Task list**

- Status filter (`<select>`): All / Active / Completed — above the table, same style as Logs tab filters.
- Table columns:
  - **Goal** — truncated to ~60 chars with `title` for full text on hover
  - **User** — `user_id`
  - **Status** — inline badge: green `active`, muted `completed`
  - **Created** — human-readable relative time (same helper used elsewhere)
  - **Duration** — elapsed time from `created_at` to `completed_at`; shows `—` for active tasks
- Clicking a row highlights it (same `.selected` class used on the users table) and populates the right panel.

**Right panel — Task tool calls**

- Default state: "Select a task to view its tool calls." (same placeholder style as permissions panel)
- On task selection:
  - Header: task `goal` in full, `outcome` beneath it (muted, italic) if completed
  - Mini log table (same columns as Logs tab): Tool, Status, Latency, Time
  - Each row clickable → opens existing log detail drawer (no new drawer needed)

---

## Data Sources

No new backend endpoints required.

| Panel | Endpoint | Notes |
|---|---|---|
| Task list | `GET /admin/api/tasks?status=<filter>&limit=100` | Already exists |
| Tool calls | `GET /admin/api/logs?task_id=<id>` | `task_id` filter already supported |

---

## Filtering

- Status filter on the task list: a `<select>` with options All / Active / Completed.
- Changing the filter re-fetches the task list; clears the right panel selection.

---

## Error & Empty States

- Task list empty: "No tasks found." centered, muted, italic.
- Tool calls empty (task has no logged calls): "No tool calls recorded for this task."
- Fetch errors: same inline error style used elsewhere in the dashboard.

---

## Implementation Notes

- Follow existing vanilla JS / inline CSS patterns — no new dependencies.
- Reuse `.ops-grid`, `.section-box`, `.section-title`, `.selected` row class, and the existing `relTime()` / `fmtMs()` helpers.
- Reuse `openLogDrawer()` for row click on tool call rows in the right panel.
- Tab registration follows the same `switchTab()` pattern as all other tabs.
