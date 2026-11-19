"""Shared release version and dependency-free release preparation CLI."""
from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
RELEASE_HEADING = re.compile(r"^## \[([^\]\n]+)\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$", re.MULTILINE)


def read_version(root: Path = ROOT) -> str:
    value = (root / "VERSION").read_text(encoding="utf-8").strip()
    if VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError(f"Invalid version {value!r}; expected MAJOR.MINOR.PATCH without leading zeros")
    return value


def _read_release(root: Path) -> tuple[str, str, int]:
    version = read_version(root)
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    latest = RELEASE_HEADING.search(changelog)
    if latest is None or latest.group(1) != version:
        raise ValueError("VERSION must match the latest dated release entry in CHANGELOG.md")
    return version, changelog, latest.start()


def check_release(root: Path = ROOT) -> str:
    """Validate that the version and latest release notes agree."""
    return _read_release(root)[0]


def bump_release(part: str, notes: list[str], root: Path = ROOT) -> str:
    version, changelog, insertion = _read_release(root)
    if part not in ("major", "minor", "patch"):
        raise ValueError("Release part must be major, minor, or patch")
    cleaned = [note.strip() for note in notes]
    if not cleaned or any(not note or "\n" in note or "\r" in note for note in cleaned):
        raise ValueError("Provide at least one non-empty, single-line release note")
    parts = [int(value) for value in version.split(".")]
    index = ("major", "minor", "patch").index(part)
    parts[index] += 1
    for following in range(index + 1, len(parts)):
        parts[following] = 0
    new_version = ".".join(str(value) for value in parts)
    if any(entry.group(1) == new_version for entry in RELEASE_HEADING.finditer(changelog)):
        raise ValueError(f"Release {new_version} already exists in CHANGELOG.md")
    entry = (
        f"## [{new_version}] - {date.today().isoformat()}\n\n### Changed\n"
        + "".join(f"- {note}\n" for note in cleaned)
        + "\n"
    )
    updated = changelog[:insertion] + entry + changelog[insertion:]
    # Prepare both files before replacing either tracked file.
    with TemporaryDirectory(prefix=".release-", dir=root) as temporary:
        staging = Path(temporary)
        (staging / "VERSION").write_text(new_version + "\n", encoding="utf-8", newline="\n")
        (staging / "CHANGELOG.md").write_text(updated, encoding="utf-8", newline="\n")
        (staging / "CHANGELOG.md").replace(root / "CHANGELOG.md")
        (staging / "VERSION").replace(root / "VERSION")
    return new_version


APP_VERSION = read_version()


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.version",
        description="Show, check, or prepare a MAJOR.MINOR.PATCH release.",
    )
    parser.add_argument("part", nargs="?", choices=("major", "minor", "patch"))
    parser.add_argument("--note", action="append", default=[], help="Release note; repeat for multiple changes")
    parser.add_argument("--check", action="store_true", help="Check VERSION against the latest changelog entry")
    args = parser.parse_args(argv)
    if args.check and (args.part or args.note):
        parser.error("--check cannot be combined with a version bump or notes")
    if args.part and not args.note:
        parser.error("A version bump requires at least one --note")
    if args.note and not args.part:
        parser.error("--note requires a major, minor, or patch bump")
    try:
        if args.check:
            print(f"Release metadata OK: {check_release(root)}")
        elif args.part:
            version = bump_release(args.part, args.note, root)
            print(f"Prepared version {version}; review VERSION and CHANGELOG.md before committing.")
            print(f'After committing: git tag -a v{version} -m "Release {version}"')
        else:
            print(read_version(root))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: error: {exc}\n")


if __name__ == "__main__":
    main()
