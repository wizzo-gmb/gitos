#!/usr/bin/env python3
"""audit_tests.py: a read-only look at a repo's tests, by area (the v62 tests audit, WO-130).

    python audit_tests.py <repo-root> [--limit N] [--fixture-bytes N]

Finds test files by common conventions and reports, per area: the file count, the total lines, the files over the
line limit (default 1,500) and the fixtures over 1 MB. It runs no test and times none: the wall time of the suite is
the operator's to give. Stdlib only; it writes nothing.

A test file is one named `test_*.py`, `*_test.py`, `*_test.rs`, `*_test.go`, `*.test.[jt]s[x]`, `*.spec.[jt]s[x]`,
or a source file (py rs go js jsx ts tsx java kt rb cs) under a directory named `tests`, `test`, `__tests__` or
`spec`. A repo with other conventions adds them in `<home>/test-audit.json`:

    {"patterns": ["*_check.py", "qa/**/*.py"], "line_limit": 1500, "fixture_bytes": 1048576, "ignore": ["vendor"]}

(`patterns` are fnmatch globs on the repo-relative path with `/`, or on the file name when they hold no `/`;
`ignore` names directories to skip beside the built-in ones.)

An area is the test directory plus its next level (`tests/pipeline`, `pkg/tests`), or, for a test file outside a test
directory, its top-level directory. A fixture is a non-source file over the byte limit under a test directory or one
named `fixtures`, `testdata` or `__snapshots__`.

Exit 0 when it ran (findings or none), 2 on bad usage or a config it cannot read. "No test file found" and a file it
could not read are printed as themselves, never as a clean result.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

LINE_LIMIT = 1500
FIXTURE_BYTES = 1024 * 1024
HOMES = (".gitos", ".pipeline", "outputs/debug")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "dist", "build", ".tox",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".claude", ".idea", ".vscode"}
TEST_DIRS = {"tests", "test", "__tests__", "spec"}
FIXTURE_DIRS = TEST_DIRS | {"fixtures", "testdata", "__snapshots__"}
SOURCE_EXT = {".py", ".rs", ".go", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".rb", ".cs"}
NAME_RE = re.compile(r"^(test_.*\.py|.*_test\.(py|rs|go)|.*\.(test|spec)\.[jt]sx?)$")


def load_config(root: Path) -> dict:
    """The repo's `<home>/test-audit.json`, or {}. A file that is there and unreadable raises ValueError."""
    for h in HOMES:
        p = root / h / "test-audit.json"
        if p.is_file():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                raise ValueError(f"{p}: {e}")
            if not isinstance(cfg, dict):
                raise ValueError(f"{p}: expected a JSON object")
            return cfg
    return {}


def is_test_file(rel: str, parts: list, patterns: list) -> bool:
    name = parts[-1]
    if NAME_RE.match(name):
        return True
    if any(d in TEST_DIRS for d in parts[:-1]) and Path(name).suffix in SOURCE_EXT and name != "__init__.py":
        return True
    for pat in patterns:
        if fnmatch.fnmatchcase(rel if "/" in pat else name, pat):
            return True
    return False


def area_of(parts: list) -> str:
    dirs = parts[:-1]
    for i, d in enumerate(dirs):
        if d in TEST_DIRS:
            return "/".join(dirs[: i + 2])
    return dirs[0] if dirs else "."


def audit(root: Path, line_limit: int, fixture_bytes: int, patterns: list, ignore: set) -> dict:
    areas: dict = {}
    unreadable: list = []

    def slot(a: str) -> dict:
        return areas.setdefault(a, {"files": 0, "lines": 0, "over": [], "fixtures": []})

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d not in ignore)
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            rel = full.relative_to(root).as_posix()
            parts = rel.split("/")
            try:
                size = full.stat().st_size
            except OSError:
                unreadable.append(rel)
                continue
            if is_test_file(rel, parts, patterns):
                try:
                    with open(full, "rb") as f:
                        lines = sum(chunk.count(b"\n") for chunk in iter(lambda: f.read(1 << 20), b""))
                        if size and not lines:
                            lines = 1
                except OSError:
                    unreadable.append(rel)
                    continue
                s = slot(area_of(parts))
                s["files"] += 1
                s["lines"] += lines
                if lines > line_limit:
                    s["over"].append((rel, lines))
            elif size > fixture_bytes and any(d in FIXTURE_DIRS for d in parts[:-1]):
                slot(area_of(parts))["fixtures"].append((rel, size))
    return {"areas": areas, "unreadable": unreadable}


def render(result: dict, line_limit: int, fixture_bytes: int) -> str:
    areas = result["areas"]
    out: list = []
    if not areas:
        out.append("tests: no test file found by the built-in conventions (test_*.py, *_test.py|rs|go, "
                   "*.test|spec.[jt]s[x], source under tests/ test/ __tests__/ spec/); this is not a clean result. "
                   "A repo with other conventions lists them in <home>/test-audit.json.")
    else:
        rows = [("area", "files", "lines", f"over {line_limit}", f"fixtures >{fixture_bytes // (1024 * 1024) or 1} MB")]
        for a in sorted(areas, key=lambda k: (-areas[k]["lines"], k)):
            s = areas[a]
            rows.append((a, str(s["files"]), str(s["lines"]), str(len(s["over"])), str(len(s["fixtures"]))))
        w = [max(len(r[i]) for r in rows) for i in range(5)]
        for i, r in enumerate(rows):
            out.append("  ".join(c.ljust(w[j]) if j == 0 else c.rjust(w[j]) for j, c in enumerate(r)))
            if i == 0:
                out.append("  ".join("-" * x for x in w))
        files = sum(s["files"] for s in areas.values())
        lines = sum(s["lines"] for s in areas.values())
        over = sorted((o for s in areas.values() for o in s["over"]), key=lambda t: -t[1])
        fix = sorted((o for s in areas.values() for o in s["fixtures"]), key=lambda t: -t[1])
        out.append(f"total: {files} test file(s), {lines} line(s) in {len(areas)} area(s); "
                   f"{len(over)} over the limit; {len(fix)} large fixture(s)")
        for rel, n in over:
            out.append(f"OVER {n} lines (limit {line_limit}): {rel}")
        for rel, n in fix:
            out.append(f"FIXTURE {n / (1024 * 1024):.1f} MB: {rel}")
    for rel in result["unreadable"]:
        out.append(f"UNREAD (not counted): {rel}")
    return "\n".join(out)


def main(argv: list) -> int:
    args = list(argv)
    opts = {}
    for flag in ("--limit", "--fixture-bytes"):
        if flag in args:
            i = args.index(flag)
            try:
                opts[flag] = int(args[i + 1])
            except (IndexError, ValueError):
                print(f"audit_tests: {flag} takes an integer", file=sys.stderr)
                return 2
            del args[i : i + 2]
    if len(args) != 1:
        print("usage: audit_tests.py <repo-root> [--limit N] [--fixture-bytes N]", file=sys.stderr)
        return 2
    root = Path(args[0])
    if not root.is_dir():
        print(f"audit_tests: {root} is not a directory", file=sys.stderr)
        return 2
    try:
        cfg = load_config(root)
        limit = opts.get("--limit", cfg.get("line_limit", LINE_LIMIT))
        fbytes = opts.get("--fixture-bytes", cfg.get("fixture_bytes", FIXTURE_BYTES))
        patterns = [str(p) for p in cfg.get("patterns", [])]
        ignore = {str(x) for x in cfg.get("ignore", [])}
        if not isinstance(limit, int) or not isinstance(fbytes, int):
            raise ValueError("line_limit and fixture_bytes must be integers")
    except (ValueError, TypeError) as e:
        print(f"audit_tests: bad config: {e}", file=sys.stderr)
        return 2
    print(render(audit(root.resolve(), limit, fbytes, patterns, ignore), limit, fbytes))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
