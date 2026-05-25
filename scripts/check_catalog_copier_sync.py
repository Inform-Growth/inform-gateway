"""Verify that copier.yml's `integrations` multi-select choices and
`catalog/catalog.yaml`'s integrations dict have the exact same set of slugs.

This guard catches the failure mode where someone adds a bundle to the catalog
but forgets to add it to copier.yml (or vice versa). Run by CI on every PR.

Exit codes:
    0 — in sync
    1 — drift detected (prints details and exits non-zero)
    2 — bad input (file missing or malformed)
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_MANIFEST = REPO_ROOT / "catalog" / "catalog.yaml"
COPIER_FILE = REPO_ROOT / "copier.yml"


def _catalog_slugs(manifest_path: Path = CATALOG_MANIFEST) -> set[str]:
    if not manifest_path.exists():
        print(f"error: {manifest_path} not found", file=sys.stderr)
        sys.exit(2)
    data = yaml.safe_load(manifest_path.read_text())
    if not isinstance(data, dict) or "integrations" not in data:
        print(f"error: {manifest_path} is malformed (no 'integrations' key)", file=sys.stderr)
        sys.exit(2)
    return set(data["integrations"].keys())


def _copier_choice_slugs(copier_path: Path = COPIER_FILE) -> set[str]:
    if not copier_path.exists():
        print(f"error: {copier_path} not found", file=sys.stderr)
        sys.exit(2)
    data = yaml.safe_load(copier_path.read_text())
    integrations = (data or {}).get("integrations") or {}
    choices = integrations.get("choices")
    if not isinstance(choices, dict):
        print(
            "error: copier.yml's `integrations.choices` must be a dict "
            "(label → slug), so we can extract the slug set.",
            file=sys.stderr,
        )
        sys.exit(2)
    return set(choices.values())


def main() -> int:
    catalog = _catalog_slugs(CATALOG_MANIFEST)
    copier = _copier_choice_slugs(COPIER_FILE)
    missing_in_copier = catalog - copier
    extra_in_copier = copier - catalog
    if not missing_in_copier and not extra_in_copier:
        print(f"✓ catalog and copier.yml in sync ({len(catalog)} integrations)")
        return 0
    if missing_in_copier:
        print("DRIFT: in catalog/catalog.yaml but missing from copier.yml `choices`:")
        for slug in sorted(missing_in_copier):
            print(f"  - {slug}")
    if extra_in_copier:
        print("DRIFT: in copier.yml `choices` but missing from catalog/catalog.yaml:")
        for slug in sorted(extra_in_copier):
            print(f"  - {slug}")
    print(
        "\nFix: update copier.yml's integrations.choices to match the catalog manifest "
        "(both must enumerate the same slugs)."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
