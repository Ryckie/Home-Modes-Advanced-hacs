"""Release hygiene: versions agree, brand files exist, docs match the tree, no network code."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "home_modes"
MANIFEST = json.loads((INTEGRATION / "manifest.json").read_text())
VERSION = MANIFEST["version"]


def test_manifest_has_the_keys_hacs_requires() -> None:
    """HACS requires domain, documentation, issue_tracker, codeowners, name and version."""
    for key in ("domain", "documentation", "issue_tracker", "codeowners", "name", "version"):
        assert MANIFEST.get(key), key
    assert MANIFEST["requirements"] == []  # no external Python dependencies
    hacs = json.loads((ROOT / "hacs.json").read_text())
    assert hacs["name"]
    assert hacs["homeassistant"] == "2026.10.4"


def test_changelog_has_the_current_version() -> None:
    """The release workflow needs a section for the manifest version."""
    text = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{VERSION}]" in text
    assert "## [Unreleased]" in text


def test_release_script_accepts_the_matching_tag_and_rejects_others(tmp_path: Path) -> None:
    """release_info.py: tag = manifest version, notes written, pre-release flag set."""
    script = ROOT / ".github" / "scripts" / "release_info.py"
    notes = tmp_path / "notes.md"
    ok = subprocess.run(
        [sys.executable, "-I", str(script), f"v{VERSION}", "--notes", str(notes)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ok.returncode == 0, ok.stderr
    assert "prerelease=true" in ok.stdout  # 0.x is a pre-release
    assert "First public beta" in notes.read_text()
    bad = subprocess.run(
        [sys.executable, "-I", str(script), "v9.9.9"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert bad.returncode != 0


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_brand_images_have_the_documented_sizes() -> None:
    """icon 256 / 512 square; logo shortest side 128-256 (256-512 for @2x)."""
    brand = INTEGRATION / "brand"
    assert _png_size(brand / "icon.png") == (256, 256)
    assert _png_size(brand / "icon@2x.png") == (512, 512)
    for name, low, high in (("logo.png", 128, 256), ("logo@2x.png", 256, 512)):
        assert low <= min(_png_size(brand / name)) <= high, name


def test_repo_layout_doc_matches_the_tree() -> None:
    """Every module, workflow, blueprint and top-level file is listed, and nothing else."""
    doc = (ROOT / "docs" / "repo-layout.md").read_text()
    expected = [
        *(p.name for p in INTEGRATION.glob("*.py")),
        *(p.name for p in (INTEGRATION / "brand").glob("*.png")),
        *(p.name for p in (ROOT / "blueprints" / "automation" / "home_modes").glob("*.yaml")),
        *(p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")),
        *(p.name for p in (ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")),
        *(p.name for p in ROOT.iterdir() if p.is_file() and not p.name.startswith(".")),
    ]
    for name in expected:
        assert name in doc, f"{name} missing from docs/repo-layout.md"
    # every file name in the listing's first block exists
    listed = re.findall(r"^  ([a-z_]+\.py)\s", doc, flags=re.M)
    for name in listed:
        assert (INTEGRATION / name).exists(), f"{name} listed but missing"


def test_every_doc_is_linked_from_the_readme() -> None:
    """Each markdown file in docs/ is reachable from the README."""
    readme = (ROOT / "README.md").read_text()
    for path in (ROOT / "docs").glob("*.md"):
        assert f"docs/{path.name}" in readme, path.name


def test_blueprint_import_links_in_the_docs_are_correct() -> None:
    """The my.home-assistant.io links point at the real files on the default branch."""
    docs = (ROOT / "docs" / "examples.md").read_text() + (ROOT / "README.md").read_text()
    for blueprint in (ROOT / "blueprints" / "automation" / "home_modes").glob("*.yaml"):
        source = yaml.safe_load(_strip_tags(blueprint))["blueprint"]["source_url"]
        link = (
            "https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url="
            + urllib.parse.quote(source, safe="")
        )
        assert link in docs, blueprint.name


def _strip_tags(path: Path) -> str:
    return re.sub(r"!input\s+\S+", "x", path.read_text())


def test_python_has_no_network_or_dynamic_code() -> None:
    """No sockets, HTTP clients, subprocesses, eval/exec or pickle in the integration."""
    forbidden_modules = {
        "socket",
        "urllib",
        "http.client",
        "requests",
        "aiohttp",
        "httpx",
        "ftplib",
        "smtplib",
        "telnetlib",
        "websockets",
        "subprocess",
        "pickle",
        "ssl",
    }
    forbidden_calls = {"eval", "exec", "__import__", "compile"}
    forbidden_helpers = {"async_get_clientsession", "async_create_clientsession"}
    for path in INTEGRATION.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            for name in names:
                root = name.split(".")[0]
                assert root not in forbidden_modules and name not in forbidden_modules, (
                    path.name,
                    name,
                )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls, (path.name, node.func.id)
            if isinstance(node, ast.Attribute | ast.Name):
                ident = node.attr if isinstance(node, ast.Attribute) else node.id
                assert ident not in forbidden_helpers, (path.name, ident)


def test_workflows_follow_the_ci_rules() -> None:
    """No secrets, explicit minimal permissions, pinned major versions, Python 3.14."""
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = path.read_text()
        data = yaml.safe_load(text)
        assert "permissions" in data, path.name
        assert "secrets." not in text.replace("secrets.GITHUB_TOKEN", ""), path.name
        for use in re.findall(r"uses:\s*(\S+)", text):
            if use.startswith("./"):
                continue
            assert "@" in use, use
    tests = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert 'PYTHON_VERSION: "3.14"' in tests


@pytest.mark.parametrize("name", ["README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md"])
def test_release_documents_exist(name: str) -> None:
    """The standard community files are present."""
    assert (ROOT / name).read_text().strip()
    assert (ROOT / "CODE_OF_CONDUCT.md").exists()
    assert (ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md").exists()
