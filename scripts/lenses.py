#!/usr/bin/env python3
"""lenses.py - which lenses are active in a repo (WO-091). Standard library only.

Lenses are OFF by default. `<home>/lenses.json` (committed with the repo) turns them on:

    {"enabled": true, "global": ["name", ...], "repo_off": ["name", ...]}

A missing file means off. Only a literal JSON `true` for `enabled` turns lenses on; a malformed
file means off and is reported. `global` names global-library lenses explicitly (no wildcard).
`repo_off` names repo-layer lenses that stay inactive without being deleted. The active set is the
repo-layer lenses not in `repo_off`, plus the selected global lenses; on a name collision the repo
lens wins. The global library is `--global-dir`, else $GITOS_GLOBAL_LENS_DIR, else `<skill>/agents`.

    lenses.py status [ROOT]
    lenses.py enable | disable                [--root ROOT]
    lenses.py select | deselect NAME...       [--root ROOT] [--global-dir D]
    lenses.py repo-off | repo-on NAME...      [--root ROOT]

Writes are atomic and keep unrelated keys. `select` refuses a name not in the global library.
`disable` keeps the lists.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

SETTING = "lenses.json"
GLOBAL_LENS_ENV = "GITOS_GLOBAL_LENS_DIR"


def resolve_home(root) -> Path:
    root = Path(root)
    return root / ".gitos" if (root / ".gitos").is_dir() else root


def global_dir(override=None) -> Path:
    return Path(override or os.environ.get(GLOBAL_LENS_ENV) or (Path(__file__).resolve().parents[1] / "agents"))


def load(home) -> dict:
    """{"state": missing|off|on|malformed, "enabled": bool, "global": [...], "repo_off": [...],
    "error": str|None, "raw": dict}. Anything but a valid file with a literal `true` is not on."""
    path = Path(home) / SETTING
    out = {"state": "missing", "enabled": False, "global": [], "repo_off": [], "error": None, "raw": {}}
    if not path.is_file():
        return out

    def bad(msg):
        out.update(state="malformed", enabled=False, error=msg)
        return out
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        return bad(f"{SETTING} is not readable JSON ({e})")
    if not isinstance(raw, dict):
        return bad(f"{SETTING} is not a JSON object")
    out["raw"] = raw
    if "enabled" in raw and not isinstance(raw["enabled"], bool):
        return bad('"enabled" must be a JSON true or false')
    for key in ("global", "repo_off"):
        v = raw.get(key, [])
        if not isinstance(v, list) or not all(isinstance(n, str) and n for n in v):
            return bad(f'"{key}" must be a list of lens names')
        out[key] = list(dict.fromkeys(v))
    out["enabled"] = raw.get("enabled") is True
    out["state"] = "on" if out["enabled"] else "off"
    return out


def lens_names(layer_dir) -> list:
    d = Path(layer_dir)
    return sorted(p.stem for p in d.glob("*.md") if p.name != "index.md") if d.is_dir() else []


def active(home, global_dir_=None) -> list:
    """[{"name", "layer"}] of the active lenses: repo lenses not in repo_off, then the selected global
    lenses that exist in the global library and are not shadowed by a repo lens. Off -> []."""
    cfg = load(home)
    if cfg["state"] != "on":
        return []
    repo_all = lens_names(Path(home) / "agents")
    repo = [n for n in repo_all if n not in cfg["repo_off"]]
    gnames = set(lens_names(global_dir(global_dir_)))
    glob = [n for n in cfg["global"] if n in gnames and n not in repo_all]
    return [{"name": n, "layer": "repo"} for n in repo] + [{"name": n, "layer": "global"} for n in glob]


def inactive(home, global_dir_=None) -> list:
    act = {(a["layer"], a["name"]) for a in active(home, global_dir_)}
    rows = [{"name": n, "layer": "repo"} for n in lens_names(Path(home) / "agents") if ("repo", n) not in act]
    rows += [{"name": n, "layer": "global"} for n in lens_names(global_dir(global_dir_)) if ("global", n) not in act]
    return rows


def _write(home, raw: dict) -> None:
    home = Path(home)
    fd, tmp = tempfile.mkstemp(prefix=".lenses-", suffix=".tmp", dir=str(home))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(raw, indent=2) + "\n")
        os.replace(tmp, home / SETTING)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _editable(home) -> dict:
    cfg = load(home)
    if cfg["state"] == "malformed":
        raise ValueError(f"{cfg['error']}: fix or delete it first")
    return dict(cfg["raw"])


def set_enabled(home, value: bool) -> None:
    raw = _editable(home)
    raw["enabled"] = value
    raw.setdefault("global", [])
    raw.setdefault("repo_off", [])
    _write(home, raw)


def edit_list(home, key: str, names, add: bool, global_dir_=None) -> None:
    raw = _editable(home)
    if add and key == "global":
        have = set(lens_names(global_dir(global_dir_)))
        unknown = [n for n in names if n not in have]
        if unknown:
            raise ValueError(f"not in the global library: {', '.join(unknown)}")
    cur = [n for n in raw.get(key, []) if isinstance(n, str)]
    cur = list(dict.fromkeys(cur + list(names))) if add else [n for n in cur if n not in set(names)]
    raw[key] = cur
    raw.setdefault("enabled", False)
    raw.setdefault("global", [])
    raw.setdefault("repo_off", [])
    _write(home, raw)


def format_status(home, global_dir_=None) -> str:
    cfg = load(home)
    first = f"lenses: {cfg['state']}"
    if cfg["error"]:
        first += f" ({cfg['error']})"
    elif cfg["state"] == "missing":
        first += f" (no {SETTING}; off by default)"
    out = [first,
           f"global selected: {', '.join(cfg['global']) or '(none)'}",
           f"repo off: {', '.join(cfg['repo_off']) or '(none)'}"]
    for a in active(home, global_dir_):
        out.append(f"active    {a['name']}  [{a['layer']}]")
    for a in inactive(home, global_dir_):
        out.append(f"inactive  {a['name']}  [{a['layer']}]")
    return "\n".join(out)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")        # Windows consoles default to cp1252
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="lenses.py", description="which lenses are active in a repo")
    sub = ap.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status", help="show the setting and the active and inactive lenses")
    st.add_argument("root", nargs="?", default=".")
    st.add_argument("--global-dir")
    for name in ("enable", "disable", "select", "deselect", "repo-off", "repo-on"):
        p = sub.add_parser(name)
        p.add_argument("--root", default=".")
        p.add_argument("--global-dir")
        if name not in ("enable", "disable"):
            p.add_argument("names", nargs="+", metavar="NAME")
    args = ap.parse_args(argv)
    home = resolve_home(args.root)
    try:
        if args.cmd == "status":
            print(format_status(home, args.global_dir))
            return 0
        if not home.is_dir():
            print(f"lenses: no home under {args.root}", file=sys.stderr)
            return 2
        if args.cmd in ("enable", "disable"):
            set_enabled(home, args.cmd == "enable")
        else:
            key = "global" if args.cmd in ("select", "deselect") else "repo_off"
            edit_list(home, key, args.names, args.cmd in ("select", "repo-off"), args.global_dir)
    except (OSError, ValueError) as e:
        print(f"lenses: {e}", file=sys.stderr)
        return 2
    print(format_status(home, args.global_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
