"""Tests for scripts/install_integration.py.

These tests build a synthetic catalog in a tmp_path and exercise the install()
function directly. The real catalog at catalog/catalog.yaml is not touched.
"""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from scripts import install_integration as ii


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    """Build a self-contained workspace with a synthetic catalog + empty runtime."""
    catalog_dir = tmp_path / "catalog"
    bundles = catalog_dir / "integrations"
    bundles.mkdir(parents=True)

    # Python-only integration (a tiny fake "echo" tool)
    echo_dir = bundles / "echo"
    echo_dir.mkdir()
    (echo_dir / "tool.py").write_text(dedent('''\
        """Echo tool — for tests."""
        def register(mcp): pass
        '''))
    (echo_dir / "README.md").write_text("# echo\n")

    # Proxy-only integration
    pingmcp_dir = bundles / "pingmcp"
    pingmcp_dir.mkdir()
    (pingmcp_dir / "connection.json").write_text(json.dumps({
        "transport": "http",
        "url": "https://example.invalid/mcp",
    }) + "\n")
    (pingmcp_dir / "README.md").write_text("# pingmcp\n")

    # Both kind
    dual_dir = bundles / "dual"
    dual_dir.mkdir()
    (dual_dir / "tool.py").write_text("def register(mcp): pass\n")
    (dual_dir / "connection.json").write_text(
        json.dumps({"transport": "stdio", "command": "dual-mcp"}) + "\n"
    )
    (dual_dir / "README.md").write_text("# dual\n")

    manifest = {
        "version": 1,
        "integrations": {
            "echo": {
                "name": "Echo",
                "description": "echo",
                "kind": "python",
                "default_select": True,
                "env_vars": ["ECHO_KEY"],
                "register_call": "_echo_tools.register(mcp)",
            },
            "pingmcp": {
                "name": "PingMCP",
                "description": "ping",
                "kind": "proxy",
                "env_vars": [],
            },
            "dual": {
                "name": "Dual",
                "description": "dual",
                "kind": "both",
                "env_vars": [],
                "register_call": "_dual_tools.register(mcp)",
            },
        },
    }
    (catalog_dir / "catalog.yaml").write_text(yaml.safe_dump(manifest))

    runtime_dir = tmp_path / "remote-gateway" / "tools" / "integrations"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "__init__.py").touch()

    connections_file = tmp_path / "remote-gateway" / "mcp_connections.json"
    registrations_file = tmp_path / "remote-gateway" / "core" / "catalog_registrations.py"

    paths = {
        "tmp": tmp_path,
        "manifest": catalog_dir / "catalog.yaml",
        "catalog_dir": catalog_dir,
        "runtime_dir": runtime_dir,
        "connections_file": connections_file,
        "registrations_file": registrations_file,
    }
    # Monkey-patch REPO_ROOT so relative_to() in actions doesn't blow up.
    return paths


def _install(workspace: dict[str, Path], slug: str, **kw):
    return ii.install(
        slug,
        manifest_path=workspace["manifest"],
        catalog_dir=workspace["catalog_dir"],
        runtime_dir=workspace["runtime_dir"],
        connections_file=workspace["connections_file"],
        registrations_file=workspace["registrations_file"],
        **kw,
    )


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch, workspace):
    """Point REPO_ROOT at tmp so .relative_to() succeeds in action lines."""
    monkeypatch.setattr(ii, "REPO_ROOT", workspace["tmp"])


def test_unknown_slug_raises():
    with pytest.raises(KeyError):
        ii.install("nonexistent-slug-xyz")


def test_install_python_only_creates_file_and_registrations(workspace):
    actions = _install(workspace, "echo")
    assert any("CREATE" in a for a in actions)
    assert any("REGISTER" in a for a in actions)
    dst = workspace["runtime_dir"] / "echo.py"
    assert dst.exists()
    assert "Echo tool" in dst.read_text()
    reg = workspace["registrations_file"].read_text()
    assert "from tools.integrations import echo as _echo_tools" in reg
    assert "_echo_tools.register(mcp)" in reg
    assert "BEGIN integration: echo" in reg
    assert "END integration: echo" in reg


def test_install_proxy_only_merges_connection(workspace):
    actions = _install(workspace, "pingmcp")
    assert any("ADD" in a for a in actions)
    doc = json.loads(workspace["connections_file"].read_text())
    assert doc["connections"]["pingmcp"]["url"] == "https://example.invalid/mcp"


def test_install_both_kinds(workspace):
    actions = _install(workspace, "dual")
    assert any("CREATE" in a for a in actions)
    assert any("ADD" in a for a in actions)
    assert (workspace["runtime_dir"] / "dual.py").exists()
    doc = json.loads(workspace["connections_file"].read_text())
    assert "dual" in doc["connections"]


def test_idempotent_reinstall_is_no_op(workspace):
    _install(workspace, "echo")
    actions = _install(workspace, "echo")
    # Second run: file matches catalog → UNCHANGED; registration block exists → no REGISTER line
    assert any("UNCHANGED" in a for a in actions)
    assert not any("REGISTER" in a for a in actions)
    # Registration file should still contain exactly one echo block
    reg = workspace["registrations_file"].read_text()
    assert reg.count("BEGIN integration: echo") == 1


def test_existing_destination_differs_without_force_skips(workspace):
    _install(workspace, "echo")
    dst = workspace["runtime_dir"] / "echo.py"
    dst.write_text("# locally customized\n")
    actions = _install(workspace, "echo")
    assert any("SKIP" in a for a in actions)
    assert dst.read_text() == "# locally customized\n"  # untouched


def test_force_overwrites_local_changes(workspace):
    _install(workspace, "echo")
    dst = workspace["runtime_dir"] / "echo.py"
    dst.write_text("# locally customized\n")
    actions = _install(workspace, "echo", force=True)
    assert any("OVERWRITE" in a for a in actions)
    assert "Echo tool" in dst.read_text()


def test_proxy_existing_connection_differs_without_force_skips(workspace):
    _install(workspace, "pingmcp")
    # mutate the connection so it differs from catalog
    doc = json.loads(workspace["connections_file"].read_text())
    doc["connections"]["pingmcp"]["url"] = "https://changed.invalid/mcp"
    workspace["connections_file"].write_text(json.dumps(doc, indent=2) + "\n")
    actions = _install(workspace, "pingmcp")
    assert any("SKIP" in a for a in actions)
    doc = json.loads(workspace["connections_file"].read_text())
    assert doc["connections"]["pingmcp"]["url"] == "https://changed.invalid/mcp"


def test_dry_run_writes_nothing(workspace):
    actions = _install(workspace, "echo", dry_run=True)
    assert any("CREATE" in a for a in actions)
    assert not (workspace["runtime_dir"] / "echo.py").exists()
    assert not workspace["registrations_file"].exists()


def test_proxy_dry_run_writes_nothing(workspace):
    actions = _install(workspace, "pingmcp", dry_run=True)
    assert any("ADD" in a for a in actions)
    assert not workspace["connections_file"].exists()


def test_load_manifest_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ii.load_manifest(tmp_path / "does-not-exist.yaml")


def test_invalid_kind_in_manifest_raises(workspace):
    bad = yaml.safe_load(workspace["manifest"].read_text())
    bad["integrations"]["echo"]["kind"] = "bogus"
    workspace["manifest"].write_text(yaml.safe_dump(bad))
    with pytest.raises(ValueError):
        ii.get_spec("echo", ii.load_manifest(workspace["manifest"]),
                    catalog_dir=workspace["catalog_dir"])


def test_main_list_subcommand(workspace, capsys, monkeypatch):
    monkeypatch.setattr(ii, "CATALOG_MANIFEST", workspace["manifest"])
    rc = ii.main(["--list"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "echo" in captured.out
    assert "pingmcp" in captured.out
    assert "dual" in captured.out


def test_real_catalog_manifest_loads_and_specs_are_valid():
    """Smoke test against the real catalog/catalog.yaml shipped in the repo."""
    real_manifest = Path(__file__).resolve().parent.parent / "catalog" / "catalog.yaml"
    if not real_manifest.exists():
        pytest.skip("real catalog not present")
    manifest = ii.load_manifest(real_manifest)
    for slug in manifest["integrations"]:
        spec = ii.get_spec(slug, manifest)
        assert spec.kind in ii.VALID_KINDS
        if spec.has_python:
            assert (spec.bundle_dir / "tool.py").exists()
            assert spec.register_call
        if spec.has_proxy:
            assert (spec.bundle_dir / "connection.json").exists()
