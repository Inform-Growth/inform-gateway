"""Install (or update) a catalog integration into this gateway deployment.

Usage:
    python scripts/install_integration.py <slug> [--force] [--dry-run]
    python scripts/install_integration.py --list

What gets installed depends on the integration's `kind` in catalog/catalog.yaml:

- `python` integrations copy `catalog/integrations/<slug>/tool.py` to
  `remote-gateway/tools/integrations/<slug>.py` and add a registration entry to
  `remote-gateway/core/catalog_registrations.py`.
- `proxy` integrations merge `catalog/integrations/<slug>/connection.json` into
  `remote-gateway/mcp_connections.json` under `connections.<slug>`.
- `both` does both.

The destination files are considered client-owned after installation. If a
destination already exists and differs from the catalog version, the script
refuses to overwrite without `--force` so local customizations aren't lost.

After install, the script prints required env vars and a link to the
integration's README. It never modifies `remote-gateway/core/mcp_server.py`
directly — wire `register_catalog_integrations(mcp)` into mcp_server.py once
per deployment (see catalog_registrations.py docstring).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DIR = REPO_ROOT / "catalog"
CATALOG_MANIFEST = CATALOG_DIR / "catalog.yaml"
RUNTIME_INTEGRATIONS_DIR = REPO_ROOT / "remote-gateway" / "tools" / "integrations"
CONNECTIONS_FILE = REPO_ROOT / "remote-gateway" / "mcp_connections.json"
REGISTRATIONS_FILE = REPO_ROOT / "remote-gateway" / "core" / "catalog_registrations.py"

VALID_KINDS = {"python", "proxy", "both"}


@dataclass
class IntegrationSpec:
    slug: str
    name: str
    description: str
    kind: str
    env_vars: list[str]
    register_call: str | None
    bundle_dir: Path

    @property
    def has_python(self) -> bool:
        return self.kind in ("python", "both")

    @property
    def has_proxy(self) -> bool:
        return self.kind in ("proxy", "both")


def load_manifest(manifest_path: Path = CATALOG_MANIFEST) -> dict[str, Any]:
    """Read and minimally validate the catalog manifest."""
    if not manifest_path.exists():
        raise FileNotFoundError(f"Catalog manifest not found: {manifest_path}")
    data = yaml.safe_load(manifest_path.read_text())
    if not isinstance(data, dict) or "integrations" not in data:
        raise ValueError(f"Malformed catalog manifest at {manifest_path}")
    return data


def get_spec(slug: str, manifest: dict[str, Any],
             catalog_dir: Path = CATALOG_DIR) -> IntegrationSpec:
    """Look up an integration in the manifest and validate its bundle exists."""
    integrations = manifest.get("integrations", {})
    if slug not in integrations:
        available = ", ".join(sorted(integrations.keys()))
        raise KeyError(f"Unknown integration '{slug}'. Available: {available}")
    entry = integrations[slug]
    kind = entry.get("kind")
    if kind not in VALID_KINDS:
        raise ValueError(f"Integration '{slug}' has invalid kind: {kind!r}")
    spec = IntegrationSpec(
        slug=slug,
        name=entry.get("name", slug),
        description=entry.get("description", ""),
        kind=kind,
        env_vars=list(entry.get("env_vars") or []),
        register_call=entry.get("register_call"),
        bundle_dir=catalog_dir / "integrations" / slug,
    )
    if not spec.bundle_dir.is_dir():
        raise FileNotFoundError(f"Bundle directory missing: {spec.bundle_dir}")
    if spec.has_python and not (spec.bundle_dir / "tool.py").exists():
        raise FileNotFoundError(f"{slug}: kind={kind} requires tool.py in bundle")
    if spec.has_proxy and not (spec.bundle_dir / "connection.json").exists():
        raise FileNotFoundError(f"{slug}: kind={kind} requires connection.json in bundle")
    if spec.has_python and not spec.register_call:
        raise ValueError(f"{slug}: kind={kind} requires register_call in manifest")
    return spec


def _read_text_or_none(path: Path) -> str | None:
    return path.read_text() if path.exists() else None


def _install_python(spec: IntegrationSpec, *, force: bool, dry_run: bool,
                    runtime_dir: Path, registrations_file: Path) -> list[str]:
    """Install the Python tool file and ensure it's wired into catalog_registrations.py.

    Returns a list of human-readable action lines describing what was done.
    """
    actions: list[str] = []
    src = spec.bundle_dir / "tool.py"
    dst = runtime_dir / f"{spec.slug}.py"
    src_text = src.read_text()
    existing = _read_text_or_none(dst)
    if existing is None:
        actions.append(f"CREATE  {dst.relative_to(REPO_ROOT)}")
        if not dry_run:
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "__init__.py").touch(exist_ok=True)
            dst.write_text(src_text)
    elif existing == src_text:
        actions.append(f"UNCHANGED  {dst.relative_to(REPO_ROOT)} (matches catalog)")
    elif force:
        actions.append(f"OVERWRITE  {dst.relative_to(REPO_ROOT)} (--force)")
        if not dry_run:
            dst.write_text(src_text)
    else:
        actions.append(
            f"SKIP  {dst.relative_to(REPO_ROOT)} (exists and differs; pass --force to overwrite)"
        )

    reg_change = _ensure_registration(spec, registrations_file, dry_run=dry_run)
    if reg_change:
        actions.append(reg_change)
    return actions


def _install_proxy(spec: IntegrationSpec, *, force: bool, dry_run: bool,
                   connections_file: Path) -> list[str]:
    """Merge the connection snippet into mcp_connections.json under connections.<slug>."""
    actions: list[str] = []
    snippet_text = (spec.bundle_dir / "connection.json").read_text()
    snippet = json.loads(snippet_text)
    if connections_file.exists():
        doc = json.loads(connections_file.read_text())
    else:
        doc = {"connections": {}}
    doc.setdefault("connections", {})
    existing = doc["connections"].get(spec.slug)
    rel = connections_file.relative_to(REPO_ROOT)
    if existing is None:
        actions.append(f"ADD     {rel} → connections.{spec.slug}")
        doc["connections"][spec.slug] = snippet
        write = True
    elif existing == snippet:
        actions.append(f"UNCHANGED  {rel} → connections.{spec.slug} (matches catalog)")
        write = False
    elif force:
        actions.append(f"REPLACE  {rel} → connections.{spec.slug} (--force)")
        doc["connections"][spec.slug] = snippet
        write = True
    else:
        actions.append(
            f"SKIP  {rel} → connections.{spec.slug} (exists and differs; pass --force to overwrite)"
        )
        write = False
    if write and not dry_run:
        connections_file.write_text(json.dumps(doc, indent=2) + "\n")
    return actions


_REG_HEADER = '"""Auto-generated by scripts/install_integration.py — do not edit by hand.\n\n' \
    "Call register_catalog_integrations(mcp) from mcp_server.py after telemetry\n" \
    "and core tools are wired up. To install an integration, run:\n" \
    "    python scripts/install_integration.py <slug>\n" \
    'To remove one, delete its block below and the runtime file in tools/integrations/.\n"""\n' \
    "from __future__ import annotations\n\n" \
    "from typing import Any\n\n\n" \
    "def register_catalog_integrations(mcp: Any) -> None:\n"
_REG_EMPTY_BODY = "    pass  # no integrations installed yet\n"
_REG_BLOCK_RE = re.compile(
    r"(    # BEGIN integration: (?P<slug>[a-zA-Z0-9_]+)\n)(?P<body>.*?)"
    r"(    # END integration: (?P=slug)\n)",
    re.DOTALL,
)


def _ensure_registration(spec: IntegrationSpec, registrations_file: Path, *,
                         dry_run: bool) -> str | None:
    """Append (or refresh) the spec's block in catalog_registrations.py.

    Returns a human-readable action line if the file changed, else None.
    """
    if not spec.register_call:
        return None
    current = _read_text_or_none(registrations_file) or _REG_HEADER + _REG_EMPTY_BODY
    if _REG_EMPTY_BODY in current:
        current = current.replace(_REG_EMPTY_BODY, "")
    if f"# BEGIN integration: {spec.slug}\n" in current:
        return None  # idempotent — already installed
    block = (
        f"\n    # BEGIN integration: {spec.slug}\n"
        f"    from tools.integrations import {spec.slug} as _{spec.slug}_tools  # noqa: PLC0415\n"
        f"    {spec.register_call}\n"
        f"    # END integration: {spec.slug}\n"
    )
    new_content = current.rstrip() + "\n" + block
    rel = registrations_file.relative_to(REPO_ROOT)
    if not dry_run:
        registrations_file.parent.mkdir(parents=True, exist_ok=True)
        registrations_file.write_text(new_content)
    return f"REGISTER  {rel} ← {spec.slug}"


def install(slug: str, *, force: bool = False, dry_run: bool = False,
            manifest_path: Path = CATALOG_MANIFEST,
            catalog_dir: Path = CATALOG_DIR,
            runtime_dir: Path = RUNTIME_INTEGRATIONS_DIR,
            connections_file: Path = CONNECTIONS_FILE,
            registrations_file: Path = REGISTRATIONS_FILE) -> list[str]:
    """Install one integration. Returns the action log."""
    manifest = load_manifest(manifest_path)
    spec = get_spec(slug, manifest, catalog_dir=catalog_dir)
    actions: list[str] = []
    if spec.has_python:
        actions.extend(_install_python(
            spec, force=force, dry_run=dry_run,
            runtime_dir=runtime_dir, registrations_file=registrations_file,
        ))
    if spec.has_proxy:
        actions.extend(_install_proxy(
            spec, force=force, dry_run=dry_run, connections_file=connections_file,
        ))
    return actions


def _print_postinstall(spec: IntegrationSpec) -> None:
    print(f"\n✓ {spec.name}: installed")
    if spec.env_vars:
        print(f"  Required env vars: {', '.join(spec.env_vars)}")
    print(f"  See {spec.bundle_dir.relative_to(REPO_ROOT)}/README.md")


def _list_integrations(manifest: dict[str, Any]) -> None:
    print(f"{'SLUG':<14} {'KIND':<7} {'DEFAULT':<8}  NAME")
    print(f"{'-' * 14} {'-' * 7} {'-' * 8}  {'-' * 30}")
    for slug, entry in sorted(manifest.get("integrations", {}).items()):
        kind = entry.get("kind", "?")
        default = "yes" if entry.get("default_select") else "no"
        name = entry.get("name", "")
        print(f"{slug:<14} {kind:<7} {default:<8}  {name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("slug", nargs="?", help="Integration slug from catalog/catalog.yaml")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files even if they differ from the catalog")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing anything")
    parser.add_argument("--list", action="store_true",
                        help="List available integrations and exit")
    args = parser.parse_args(argv)

    manifest = load_manifest(CATALOG_MANIFEST)
    if args.list:
        _list_integrations(manifest)
        return 0
    if not args.slug:
        parser.error("slug is required unless --list is given")
    try:
        spec = get_spec(args.slug, manifest, catalog_dir=CATALOG_DIR)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    actions = install(args.slug, force=args.force, dry_run=args.dry_run)
    for line in actions:
        print(line)
    if not args.dry_run:
        _print_postinstall(spec)
    else:
        print(f"\n(dry-run — no files written; spec: {spec.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
