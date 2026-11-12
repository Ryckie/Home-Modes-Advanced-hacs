"""Check that a release tag, the manifest, hacs.json and the changelog agree.

Usage: release_info.py <tag> [--notes FILE]

Prints ``prerelease=true|false`` (for $GITHUB_OUTPUT) and, with --notes, writes the
changelog section of that version to FILE. Exits with an error message on any mismatch.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "custom_components" / "home_modes" / "manifest.json"
HACS = ROOT / "hacs.json"
CHANGELOG = ROOT / "CHANGELOG.md"
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?)$")


def changelog_section(text: str, version: str) -> str | None:
    """Return the body of the ``## [version]`` section, or None."""
    match = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    return match.group(1).strip() if match else None


def is_prerelease(version: str) -> bool:
    """0.x versions and anything with a suffix (-beta.1) are pre-releases."""
    return version.startswith("0.") or "-" in version


def check(tag: str) -> tuple[str, list[str]]:
    """Return (version, problems)."""
    problems: list[str] = []
    match = TAG_RE.match(tag)
    if not match:
        return "", [f"tag {tag!r} must look like v1.2.3 or v1.2.3-beta.1"]
    version = match.group(1)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        problems.append(f"manifest.json version is {manifest.get('version')!r}, tag is {version!r}")
    hacs = json.loads(HACS.read_text(encoding="utf-8"))
    if "name" not in hacs:
        problems.append("hacs.json has no name")
    if changelog_section(CHANGELOG.read_text(encoding="utf-8"), version) is None:
        problems.append(f"CHANGELOG.md has no '## [{version}]' section")
    return version, problems


def main() -> int:
    """Run the check."""
    parser = argparse.ArgumentParser()
    parser.add_argument("tag")
    parser.add_argument("--notes")
    args = parser.parse_args()
    version, problems = check(args.tag)
    if problems:
        for problem in problems:
            print(f"::error::{problem}", file=sys.stderr)
        return 1
    if args.notes:
        section = changelog_section(CHANGELOG.read_text(encoding="utf-8"), version) or ""
        Path(args.notes).write_text(section + "\n", encoding="utf-8")
    print(f"prerelease={'true' if is_prerelease(version) else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
