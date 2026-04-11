"""
Field Registry — Business context definitions for MCP integration fields.

Loads and validates field definitions from YAML files in
remote-gateway/context/fields/. Provides:
  - Field lookup (what does this field mean?)
  - Response validation (are all returned fields documented?)
  - Drift detection (has the integration changed its schema?)

Business Context:
    Every MCP integration returns fields with technical names that may not
    match how the business uses them. This module is the single source of
    truth for field semantics. When an integration changes a field name or
    adds new fields, drift detection surfaces that for human review.

Usage:
    registry = FieldRegistry()
    registry.lookup("stripe", "mrr")            # → field definition dict
    registry.validate_response("stripe", data)  # → ValidationResult
    registry.check_drift("stripe", fresh_data)  # → DriftResult
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

FIELDS_DIR = Path(__file__).parent.parent / "context" / "fields"


@dataclass
class ValidationResult:
    integration: str
    unknown_fields: list[str]      # in response, not in YAML
    missing_fields: list[str]      # in YAML (non-nullable), not in response
    documented_fields: list[str]   # present in both
    valid: bool                    # True if no unknown or missing required fields

    def summary(self) -> str:
        lines = [f"Field validation for '{self.integration}':"]
        lines.append(f"  Documented: {len(self.documented_fields)}")
        if self.unknown_fields:
            lines.append(f"  Unknown (not in registry): {self.unknown_fields}")
        if self.missing_fields:
            lines.append(f"  Missing required fields: {self.missing_fields}")
        if self.valid:
            lines.append("  Status: OK")
        else:
            lines.append("  Status: DRIFT DETECTED — review and update field definitions")
        return "\n".join(lines)


@dataclass
class DriftResult:
    integration: str
    new_fields: list[str]          # in fresh data, not in YAML
    removed_fields: list[str]      # in YAML, not in fresh data
    unchanged_fields: list[str]    # present in both
    has_drift: bool

    def summary(self) -> str:
        lines = [f"Drift check for '{self.integration}':"]
        if self.new_fields:
            lines.append(f"  New fields (add to YAML): {self.new_fields}")
        if self.removed_fields:
            lines.append(f"  Removed fields (remove from YAML): {self.removed_fields}")
        if not self.has_drift:
            lines.append("  No drift detected.")
        return "\n".join(lines)


class FieldRegistry:
    """Loads field definitions from YAML and provides validation utilities."""

    def __init__(self, fields_dir: Path | None = None) -> None:
        self._dir = fields_dir or FIELDS_DIR
        self._cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_integrations(self) -> list[str]:
        """Return the names of all integrations with field definitions.

        Returns:
            Sorted list of integration names (e.g., ["hubspot", "stripe"]).
        """
        return sorted(
            p.stem
            for p in self._dir.glob("*.yaml")
            if not p.stem.startswith("_")
        )

    def lookup(self, integration: str, field_name: str) -> dict[str, Any] | None:
        """Return the business definition for a single field.

        Args:
            integration: Integration slug (e.g., "stripe").
            field_name: Exact field key as returned by the integration.

        Returns:
            Field definition dict, or None if not found.
        """
        defs = self._load(integration)
        return defs.get("fields", {}).get(field_name)

    def get_all(self, integration: str) -> dict[str, Any]:
        """Return all field definitions for an integration.

        Args:
            integration: Integration slug (e.g., "stripe").

        Returns:
            Dict of field_name → definition, or empty dict if not found.
        """
        return self._load(integration).get("fields", {})

    def validate_response(
        self, integration: str, response: dict[str, Any]
    ) -> ValidationResult:
        """Check a tool response against the registered field definitions.

        Identifies fields that are undocumented (new/unknown) or missing
        (expected but absent). Does not block the response — call sites
        use this to surface drift.

        Args:
            integration: Integration slug (e.g., "stripe").
            response: Flat dict of field_name → value returned by a tool.

        Returns:
            ValidationResult with unknown, missing, and documented fields.
        """
        defined = self.get_all(integration)
        response_keys = set(response.keys())
        defined_keys = set(defined.keys())

        unknown = sorted(response_keys - defined_keys)
        documented = sorted(response_keys & defined_keys)

        required_keys = {k for k, v in defined.items() if not v.get("nullable", False)}
        missing = sorted(required_keys - response_keys)

        return ValidationResult(
            integration=integration,
            unknown_fields=unknown,
            missing_fields=missing,
            documented_fields=documented,
            valid=not unknown and not missing,
        )

    def check_drift(
        self, integration: str, fresh_sample: dict[str, Any]
    ) -> DriftResult:
        """Compare a fresh API/MCP response against stored field definitions.

        Args:
            integration: Integration slug (e.g., "stripe").
            fresh_sample: A current response dict from the integration.

        Returns:
            DriftResult describing what has changed since last discovery.
        """
        defined_keys = set(self.get_all(integration).keys())
        fresh_keys = set(fresh_sample.keys())

        return DriftResult(
            integration=integration,
            new_fields=sorted(fresh_keys - defined_keys),
            removed_fields=sorted(defined_keys - fresh_keys),
            unchanged_fields=sorted(fresh_keys & defined_keys),
            has_drift=bool(fresh_keys.symmetric_difference(defined_keys)),
        )

    def upsert(self, integration: str, definitions: dict[str, Any]) -> None:
        """Write or update field definitions for an integration.

        Called by the discover_fields tool after AI-generated definitions
        have been reviewed. Merges new fields into existing YAML without
        overwriting manually-curated descriptions.

        Args:
            integration: Integration slug (e.g., "stripe").
            definitions: Dict matching the YAML schema (must include "fields" key).
        """
        path = self._dir / f"{integration}.yaml"
        existing: dict[str, Any] = {}

        if path.exists():
            with open(path) as f:
                existing = yaml.safe_load(f) or {}

        # Merge: preserve existing field descriptions, add new fields
        existing_fields: dict[str, Any] = existing.get("fields", {})
        new_fields: dict[str, Any] = definitions.get("fields", {})
        merged_fields = {**new_fields, **existing_fields}  # existing takes precedence

        output = {**existing, **definitions, "fields": merged_fields}

        with open(path, "w") as f:
            yaml.dump(output, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        # Bust cache
        self._cache.pop(integration, None)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self, integration: str) -> dict[str, Any]:
        if integration in self._cache:
            return self._cache[integration]

        path = self._dir / f"{integration}.yaml"
        if not path.exists():
            return {}

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        self._cache[integration] = data
        return data


# Module-level singleton — imported by mcp_server.py
registry = FieldRegistry()
