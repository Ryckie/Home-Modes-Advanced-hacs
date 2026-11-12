"""docs/final-audit.md only cites files, symbols and tests that exist."""

from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
AUDIT = ROOT / "docs" / "final-audit.md"
FILE_EXT = r"(?:py|md|yml|yaml|json|mjs|js|png)"
FILE_RE = re.compile(rf"^[\w./@-]+\.{FILE_EXT}$")
# Names from the brief that the audit cites to say they do NOT exist (deviations).
ABSENT_BY_DESIGN = {
    "intent.py",
    "migrate.py",
    "device_trigger.py",
    "device_condition.py",
    "strings.json",
    "trigger.py",
}
SEARCH_ROOTS = [
    ROOT,
    ROOT / "custom_components" / "home_modes",
    ROOT / "tests",
    ROOT / "docs",
    ROOT / ".github" / "workflows",
    ROOT / ".github" / "scripts",
]


def _resolve(name: str) -> Path | None:
    if name.endswith("/"):
        return ROOT / name if (ROOT / name).is_dir() else None
    for base in SEARCH_ROOTS:
        if (base / name).is_file():
            return base / name
    return None


def _test_names(path: Path) -> set[str]:
    """Return the names of the test functions and methods in a test module."""
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _js_test_names(path: Path) -> set[str]:
    return set(re.findall(r"test\((?:'|\")([^'\"]+)", path.read_text()))


def collect_references() -> tuple[list[str], list[str]]:
    """Return (checked references, broken references) found in the audit."""
    checked: list[str] = []
    broken: list[str] = []
    for line in AUDIT.read_text().splitlines():
        last_file: Path | None = None
        for token in re.findall(r"`([^`]+)`", line):
            token = token.strip()
            file_part, _, member = token.partition("::")
            if "::" not in token and not FILE_RE.match(token):
                # a bare test name that continues the previous "file::test" of the same line
                if re.fullmatch(r"test_[\w*]+", token) and last_file is not None:
                    file_part, member = last_file.name, token
                else:
                    continue
            if "<" in token or ("/" in token and token.endswith("/") and "::" not in token):
                if token.endswith("/") and _resolve(token) is None:
                    broken.append(token)
                    checked.append(token)
                continue
            path = _resolve(file_part)
            checked.append(token if member else file_part)
            if file_part in ABSENT_BY_DESIGN:
                if path is not None:
                    broken.append(f"{token} (listed as absent, but exists)")
                continue
            if path is None:
                broken.append(token)
                continue
            last_file = path
            if not member:
                continue
            if path.suffix == ".py" and path.parent.name == "tests":
                names = _test_names(path)
                ok = (
                    any(fnmatch.fnmatch(n, member) for n in names)
                    if "*" in member
                    else member in names
                )
            elif path.suffix == ".py":
                ok = re.search(rf"\b{re.escape(member)}\b", path.read_text()) is not None
            else:
                ok = member in path.read_text()
            if not ok:
                broken.append(token)
    return checked, broken


def test_every_reference_in_the_audit_exists() -> None:
    """Paths, test names and symbols cited in the audit resolve to real things."""
    checked, broken = collect_references()
    assert len(checked) > 100  # the parser really found the references
    assert not broken, broken


def test_js_tests_cited_exist() -> None:
    """The jsdom test file the audit cites is present."""
    assert _js_test_names(ROOT / "tests" / "js" / "cards.test.mjs")
