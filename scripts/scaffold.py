"""Scaffold a project's GitOS pipeline (+ optional brain).

Lays the working-system structure into a target repo: the `.gitos/` work-order
ledger, the three role pointers, the handoff skeleton, and — by default — the
per-repo brain. Also writes a project-scoped memory pointer so the role survives
context compaction.

The script lays empty/skeleton files and — unless `--git skip` — ensures the repo is
under version control: with `--git ensure` (default) it reports its intent, then runs
`git init` + lays a starter `.gitignore`/`.gitattributes` when no repo is detected
(robust detection: `.git` as a dir or file, or a parent work-tree). It does NOT ingest,
fill the handoff, or COMMIT — those are agent/operator actions (see
references/roles/inception.md; the initial baseline commit is the inception agent's step).
It is idempotent: it creates missing files but never overwrites existing ones, and never
re-inits a repo that is already under git, so re-running fills gaps without clobbering state.

Usage:
    python scaffold.py <PROJECT_ROOT>
        [--home {auto,.gitos,.pipeline,outputs/debug,docs/agents}]   default: auto
        [--brain {on,off}]                                    default: on
        [--roles {all,diagnostic}]                            default: all
        [--domain <hint>]                                     default: none (generic)
        [--git {ensure,offer,skip}]                           default: ensure

Home detection (`--home auto`, first match wins):
    1. existing <root>/.gitos/         -> use it (unified home)
    2. existing <root>/outputs/debug/  -> adopt in place (LEGACY back-compat)
    3. existing <root>/.pipeline/      -> use it (LEGACY)
    4. existing <root>/docs/agents/    -> use it
    5. none of the above               -> create <root>/.gitos/  (unified default)

`--roles diagnostic --brain off` reproduces the legacy diagnostic-only file set.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"

ROLES = ("inception", "orchestrator", "diagnostic")


def engine_version() -> "int | None":
    """The engine's ENGINE_VERSION from the skill's VERSION file (None if unreadable)."""
    try:
        return int((SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def find_bridge(root: Path, home: Path) -> "str | None":
    """Return the repo-relative POSIX path to a BRIDGE.md, or None.

    Mirrors the upgrade Step-0 scan precedence (references/upgrade.md / WO-005):
    <root>/BRIDGE.md -> <root>/prompts/BRIDGE.md -> <home>/BRIDGE.md. First hit wins.
    A bridge marks the repo as a profiled (Custom) product; its absence means Standard.
    """
    for cand in (root / "BRIDGE.md", root / "prompts" / "BRIDGE.md", home / "BRIDGE.md"):
        if cand.is_file():
            try:
                return cand.resolve().relative_to(root).as_posix()
            except ValueError:
                return str(cand).replace("\\", "/")
    return None


ROLE_SUMMARIES = {
    "inception": (
        "One-time bootstrapper. Runs a short interview, scaffolds the pipeline + the "
        "brain, seeds the brain at the chosen depth, fills HANDOFF.md, ensures version "
        "control (auto-inits git if absent), then hands control to the orchestrator. Sets "
        "up the working SYSTEM, not application source."
    ),
    "orchestrator": (
        "Front-line builder + coordinator. Each session reads HANDOFF.md (once) + "
        "INDEX.md + the brain. Builds with the user; authors and prioritizes "
        "work-orders; invokes the diagnostic finder for evidence; dispatches and "
        "verifies implementer agents; stewards the brain (inline upsert -> checkpoint "
        "reconcile -> brain_lint), recording a decision page on every non-trivial "
        "choice. May authorize edits."
    ),
    "diagnostic": (
        "Read-only finder. Builds the log/output vocabulary, scans the nine anomaly "
        "families, and writes evidence-first work-orders into the INDEX. Never edits "
        "production code. Invoked by the orchestrator for evidence, or directly by the "
        "operator ('audit this')."
    ),
}


def project_memory_dirname(project_root: Path) -> str:
    """Convert an absolute project path to the auto-memory directory name.

    Examples:
        D:\\projects\\my-app       ->  d--projects-my-app
        /home/user/projects/foo    ->  home-user-projects-foo
    """
    abs_str = str(project_root.resolve()).replace("\\", "/")
    if ":" in abs_str:
        drive, rest = abs_str.split(":", 1)
        drive = drive.lower()
        rest = rest.lstrip("/").rstrip("/").replace("/", "-")
        return f"{drive}--{rest}"
    rest = abs_str.lstrip("/").rstrip("/").replace("/", "-")
    return rest


def write_if_missing(path: Path, content: str) -> bool:
    """Write content to path only if it doesn't exist. Returns True if written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def gitkeep(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    keep = path / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")


def read_template(rel: str) -> str:
    tpl = ASSETS / rel
    if not tpl.exists():
        raise FileNotFoundError(f"missing template: {tpl}")
    return tpl.read_text(encoding="utf-8")


def render(text: str, **tokens: str) -> str:
    """Substitute {{KEY}} tokens via literal replace (safe with JSON/YAML braces)."""
    for key, val in tokens.items():
        text = text.replace("{{" + key + "}}", val)
    return text


CLAUDE_ANCHOR_START = "<!-- gitos:agent-system START -->"
CLAUDE_ANCHOR_END = "<!-- gitos:agent-system END -->"


def carried_lines(old_block: str, new_block: str) -> "list[str]":
    """Lines inside the OLD managed block that the refreshed block does not account for.

    The block is engine-managed, so a refresh SHOULD replace drifted engine text — that is
    its entire purpose. But content the engine never wrote (a profile `_meta` pointer, an
    operator note) must survive that refresh: destroying it is silent data loss (WO-029
    class 6). difflib separates the two deterministically:

      * `delete` opcodes — old lines with no counterpart at all in the incoming block. This
        is foreign content: carried.
      * `replace` opcodes — an old line swapped for a similar new one, i.e. ordinary drift.
        Carried ONLY when the line has no close counterpart among the incoming lines
        (difflib's own documented 0.6 cutoff), which catches a wholly-rewritten block
        without treating normal drift as content.

    Blank lines are never content. Relative order is preserved. `autojunk=False` keeps the
    result deterministic regardless of block size.

    Known trade-off: the engine cannot know what an OLDER template said, so a line a future
    template legitimately RETIRES is carried forward rather than dropped. That errs toward
    preserving, and the carry is always REPORTED — never silent. Deleting it is then a
    visible one-line operator edit; the reverse (a silent delete) is unrecoverable.
    """
    old_lines = old_block.splitlines()
    new_lines = new_block.splitlines()
    out: list[str] = []
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag not in ("delete", "replace"):
            continue
        cand = new_lines[j1:j2] if tag == "replace" else []
        for line in old_lines[i1:i2]:
            if not line.strip():
                continue                      # blank lines are never content
            if cand and difflib.get_close_matches(line, cand, n=1, cutoff=0.6):
                continue                      # ordinary drift: a successor is in the new block
            out.append(line)
    return out


def ensure_claude_section(claude_path: Path, section: str) -> "tuple[str, list[str]]":
    """Upsert the gitos managed block (the canary's durable recovery seed, WO-028) into a
    repo-root CLAUDE.md — the harness re-injects CLAUDE.md into every context window, so the
    marker requirement + recovery trigger survive here even when the skill directive washes
    out. MANAGED BLOCK ONLY: content outside the START/END markers is never touched.

    NEVER SILENTLY DELETES (WO-029 class 6). Content found inside the block that the refresh
    does not account for is CARRIED THROUGH — re-emitted just inside the END marker — and
    reported to the caller. It is preserved in place rather than relocated outside the
    markers, because moving it would violate the one invariant this function guarantees:
    content outside the markers is never touched.

    -> (status, carried) where status is 'created' (no file), 'updated' (block replaced),
       'preserved' (block replaced AND unrecognized in-block lines carried through),
       'unchanged' (idempotent no-op), or 'appended' (file existed without the block), and
       `carried` lists the lines carried through. Never raises on ordinary content.
    """
    block = section.rstrip("\n")
    if not claude_path.exists():
        claude_path.parent.mkdir(parents=True, exist_ok=True)
        claude_path.write_text(block + "\n", encoding="utf-8")
        return "created", []
    existing = claude_path.read_text(encoding="utf-8")
    if CLAUDE_ANCHOR_START in existing and CLAUDE_ANCHOR_END in existing:
        i = existing.index(CLAUDE_ANCHOR_START)
        j = existing.index(CLAUDE_ANCHOR_END, i) + len(CLAUDE_ANCHOR_END)
        carried = carried_lines(existing[i:j], block)
        new_block = block
        if carried:
            # re-emit the unrecognized lines just inside the END marker: stable (a re-run
            # finds them there and carries them to the same place -> idempotent).
            if CLAUDE_ANCHOR_END in block:
                head = block[:block.rindex(CLAUDE_ANCHOR_END)].rstrip("\n")
                new_block = (head + "\n\n" + "\n".join(carried) + "\n"
                             + CLAUDE_ANCHOR_END)
            else:                              # markerless section: never drop the content
                new_block = block + "\n" + "\n".join(carried)
        new = existing[:i] + new_block + existing[j:]      # preserve everything outside
        if new == existing:
            return "unchanged", carried
        claude_path.write_text(new, encoding="utf-8")
        return ("preserved" if carried else "updated"), carried
    sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    claude_path.write_text(existing + sep + block + "\n", encoding="utf-8")
    return "appended", []


def detect_home(root: Path, requested: str) -> tuple[Path, str]:
    """Return (home_dir, label). label in {'.gitos','.pipeline','outputs/debug','docs/agents'}."""
    if requested != "auto":
        return root / requested, requested
    if (root / ".gitos").is_dir():
        return root / ".gitos", ".gitos"
    if (root / "outputs" / "debug").is_dir():
        return root / "outputs" / "debug", "outputs/debug"
    if (root / ".pipeline").is_dir():
        return root / ".pipeline", ".pipeline"
    if (root / "docs" / "agents").is_dir():
        return root / "docs" / "agents", "docs/agents"
    return root / ".gitos", ".gitos"


def report(written: bool, path: Path, base: Path) -> None:
    try:
        rel = path.relative_to(base)
    except ValueError:
        rel = path
    print(f"{'OK   wrote' if written else 'SKIP exists'} {rel}")


# --------------------------------------------------------------------------- git (WO-011)
# gitos guarantees version control: the .gitos/ ledger + brain are only a durable audit
# trail under git, so `--git ensure` (default) inits a repo when none is found. See the
# ADR brain/wiki/decisions/ensure-git-at-init.md and references/roles/inception.md.

STARTER_GITATTRIBUTES = (
    "# Normalize line endings: store LF in the repo, check out native per platform.\n"
    "* text=auto\n"
)


def has_git(root: Path) -> bool:
    """Robust 'is this path under version control?' check.

    Stricter than the naive `(root/'.git').is_dir()`: `.exists()` catches `.git` as a
    DIR *or* a FILE (git worktrees / submodules use a `gitdir:` pointer file), and
    `git rev-parse --is-inside-work-tree` catches parent-repo nesting (a project root
    that sits inside an outer repo with no local `.git`). Missing git binary -> False.
    """
    if (root / ".git").exists():
        return True
    try:
        cp = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            text=True, capture_output=True,
        )
    except OSError:
        return False
    return cp.returncode == 0 and cp.stdout.strip() == "true"


def git_init(root: Path) -> bool:
    """Run `git init` on `root`. Returns True on success. Never raises: a missing git
    binary or a non-zero return prints a clear warning and returns False (scaffold still
    succeeds — it laid its files; ensuring git is best-effort if the environment lacks it)."""
    try:
        cp = subprocess.run(["git", "init", str(root)], text=True, capture_output=True)
    except OSError:
        print("GIT  WARNING: git executable not found — could not initialize a repo. "
              "Install git, then run `git init` here so the audit trail is durable.")
        return False
    if cp.returncode != 0:
        print(f"GIT  WARNING: `git init` failed (rc={cp.returncode}): "
              f"{(cp.stderr or cp.stdout).strip()[:200]}")
        return False
    return True


def starter_gitignore(home_label: str, brain_on: bool) -> str:
    """A generic starter .gitignore: ignore caches/editor cruft, but NEVER the pipeline
    home (the audit trail). Profiles/projects extend it. Home-aware so it tracks the
    configured home (.gitos/.pipeline/...) rather than hard-coding `.gitos/`."""
    lines = [
        "# gitos starter .gitignore — generic; extend per project/profile.",
        f"# The pipeline home '{home_label}/' is the audit trail and is intentionally NOT ignored.",
        "",
        "# Python",
        "__pycache__/",
        "*.py[cod]",
        "*.egg-info/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        "",
        "# Editors / OS",
        ".idea/",
        ".vscode/",
        "*.swp",
        ".DS_Store",
        "Thumbs.db",
    ]
    if brain_on:
        lines += [
            "",
            "# Brain extracted-text cache (regenerable from raw/) — keep the dir, drop the cache.",
            f"{home_label}/brain/raw/_extracted/*",
            f"!{home_label}/brain/raw/_extracted/.gitkeep",
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold a GitOS pipeline + brain.")
    ap.add_argument("root")
    ap.add_argument("--home", default="auto",
                    choices=["auto", ".gitos", ".pipeline", "outputs/debug", "docs/agents"])
    ap.add_argument("--brain", default="on", choices=["on", "off"])
    ap.add_argument("--roles", default="all", choices=["all", "diagnostic"])
    ap.add_argument("--domain", default="")
    ap.add_argument("--bridge", default="",
                    help="repo-relative path to a domain-profile BRIDGE.md; when set "
                         "(or auto-detected) the brain meta is stamped Custom (WO-005)")
    ap.add_argument("--git", default="ensure", choices=["ensure", "offer", "skip"],
                    help="ensure (default): report then `git init` if no repo is detected; "
                         "skip: no git action; offer: legacy recommend-only (never runs git)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 1

    home, home_label = detect_home(root, args.home)
    legacy = home_label == "outputs/debug"
    project_name = root.name
    today = date.today().isoformat()
    posix_root = str(root).replace("\\", "/")
    tokens = dict(PROJECT_NAME=project_name, ROOT=posix_root, DATE=today, HOME=home_label,
                  DOMAIN=args.domain or "(generic)")

    home.mkdir(parents=True, exist_ok=True)
    print(f"OK   home = {home_label}{'  (LEGACY adopt-in-place)' if legacy else ''}")

    # WO-005 item D: a domain-profile BRIDGE marks this repo Custom. Explicit --bridge
    # wins; else auto-scan the upgrade Step-0 precedence. None => Standard (unchanged meta).
    bridge_rel = args.bridge.strip() or find_bridge(root, home)
    if bridge_rel:
        print(f"OK   profile bridge detected -> {bridge_rel} (repo classified Custom)")

    diagnostic_only = args.roles == "diagnostic"

    # ---- work side --------------------------------------------------------
    report(write_if_missing(home / "INDEX.md",
                            render(read_template("INDEX.md.tmpl"), **tokens)), home / "INDEX.md", root)
    report(write_if_missing(home / "log_vocabulary.md",
                            render(read_template("log_vocabulary.md.tmpl"), **tokens)),
           home / "log_vocabulary.md", root)
    gitkeep(home / "work-orders" / "resolved")
    print("OK   work-orders/resolved/")

    if not diagnostic_only:
        report(write_if_missing(home / "README.md",
                                render(read_template("pipeline-readme.md.tmpl"), **tokens)),
               home / "README.md", root)
        report(write_if_missing(home / "HANDOFF.md",
                                render(read_template("HANDOFF.md.tmpl"), **tokens)),
               home / "HANDOFF.md", root)

    # role pointers (all roles, or just diagnostic for legacy/back-compat)
    role_tpl = read_template("role-pointer.md.tmpl")
    target_roles = ROLES if not diagnostic_only else ("diagnostic",)
    for role in target_roles:
        rendered = render(
            role_tpl,
            ROLE=role.capitalize(),
            SKILL_BRIEF_PATH=f"~/.claude/skills/gitos/references/roles/{role}.md",
            ROLE_SUMMARY=ROLE_SUMMARIES[role],
            **tokens,
        )
        p = home / "roles" / f"{role}.md"
        report(write_if_missing(p, rendered), p, root)

    # ---- brain ------------------------------------------------------------
    if args.brain == "on" and not diagnostic_only:
        brain = home / "brain"
        report(write_if_missing(brain / "BRAIN.md",
                                render(read_template("brain/BRAIN.md.tmpl"), **tokens)),
               brain / "BRAIN.md", root)
        gitkeep(brain / "raw" / "_extracted")
        for sub in ("sources", "entities", "concepts", "decisions"):
            gitkeep(brain / "wiki" / sub)
        report(write_if_missing(brain / "wiki" / "index.md",
                                render(read_template("brain/wiki-index.md.tmpl"), **tokens)),
               brain / "wiki" / "index.md", root)
        report(write_if_missing(brain / "wiki" / "log.md",
                                render(read_template("brain/wiki-log.md.tmpl"), **tokens)),
               brain / "wiki" / "log.md", root)
        meta = {"created": today, "engine_version": engine_version(),
                "last_ingest": None, "last_lint": None,
                "counts": {"sources": 0, "entities": 0, "concepts": 0, "decisions": 0}}
        if bridge_rel:
            ev = engine_version()
            meta["bridge"] = bridge_rel
            meta["last_reconciled_engine"] = ev
            meta["min_compatible_engine"] = ev
        report(write_if_missing(brain / ".brainmeta.json",
                                json.dumps(meta, indent=2) + "\n"),
               brain / ".brainmeta.json", root)
        # Copy the lint tool into the repo so `<home>/tools/brain_lint.py` — referenced by
        # BRAIN.md and the role briefs — actually exists, and the repo can lint its own
        # brain self-contained within its home. Byte copy (preserve LF); never clobber a copy.
        repo_lint = home / "tools" / "brain_lint.py"
        if repo_lint.exists():
            print(f"SKIP exists {repo_lint.relative_to(root)}")
        else:
            repo_lint.parent.mkdir(parents=True, exist_ok=True)
            repo_lint.write_bytes((SKILL_DIR / "scripts" / "brain_lint.py").read_bytes())
            print(f"OK   wrote {repo_lint.relative_to(root)}")
        print("OK   brain laid (page templates live in the skill: assets/brain/pages/)")

    # ---- state canary tool --------------------------------------------------
    # Copy the state-canary tool so `<home>/tools/canary.py` — referenced by SKILL.md
    # (## Canary) and the orchestrator brief's first-action — exists self-contained in the
    # home (the brain_lint pattern). NOT brain-gated: the canary checks the ledger, stamps,
    # lens registries, and links, which exist without a brain (it only *delegates* to
    # brain_lint when a brain is present). Byte copy (preserve LF); never clobber a copy.
    if not diagnostic_only:
        repo_canary = home / "tools" / "canary.py"
        if repo_canary.exists():
            print(f"SKIP exists {repo_canary.relative_to(root)}")
        else:
            repo_canary.parent.mkdir(parents=True, exist_ok=True)
            repo_canary.write_bytes((SKILL_DIR / "scripts" / "canary.py").read_bytes())
            print(f"OK   wrote {repo_canary.relative_to(root)}")

    # ---- agents (operator-imported steering lenses) -----------------------
    # The four roles apply on-demand "lens" context (read-on-demand approach context, NOT
    # the brain's facts). <home>/agents/index.md is the registry, empty until the first
    # `/gitos agent import`. Lands for full-role scaffolds (independent of --brain, since
    # lenses are not brain pages). write_if_missing keeps it idempotent and never clobbers
    # an operator's populated registry — the dir is created via the index.md parent.
    if not diagnostic_only:
        agents = home / "agents"
        report(write_if_missing(agents / "index.md",
                                render(read_template("agents/index.md.tmpl"), **tokens)),
               agents / "index.md", root)

    # ---- memory pointer ---------------------------------------------------
    memory_dir = Path.home() / ".claude" / "projects" / project_memory_dirname(root) / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    pointer = memory_dir / "gitos_role_brief.md"
    pointer_body = (
        f"---\nname: {project_name} gitos role brief\n"
        f"description: Reloadable pointer to the GitOS agent system for "
        f"{project_name}; load when resuming work or restoring context after compaction\n"
        f"metadata:\n  type: reference\n---\n\n"
        f"This repo runs the **GitOS** agent system. Pipeline home: "
        f"`{posix_root}/{home_label}/`.\n\n"
        f"Default re-entry role: **orchestrator**. On a fresh/compacted session, invoke the "
        f"`gitos` skill and read, in order:\n"
        f"- `{home_label}/HANDOFF.md` (birth record, once)\n"
        f"- `{home_label}/INDEX.md` (work state)\n"
        f"- `{home_label}/brain/wiki/index.md` (knowledge state)\n\n"
        f"The skill (`~/.claude/skills/gitos/`) defines the roles; the files above "
        f"hold this project's state.\n\nEstablished {today}.\n"
    )
    report(write_if_missing(pointer, pointer_body), pointer, memory_dir)

    legacy_pointer = memory_dir / "diagnostic_role_brief.md"
    if legacy_pointer.exists():
        txt = legacy_pointer.read_text(encoding="utf-8")
        if "superseded by gitos_role_brief.md" not in txt:
            legacy_pointer.write_text(
                txt + "\n\n> NOTE: superseded by gitos_role_brief.md "
                      "(diagnostic-flow was folded into gitos).\n",
                encoding="utf-8")
            print("OK   annotated legacy diagnostic_role_brief.md (superseded)")

    # legacy from before the project-flow -> gitos rename: annotate the old pointer
    legacy_pf_pointer = memory_dir / "project_flow_role_brief.md"
    if legacy_pf_pointer.exists():
        txt = legacy_pf_pointer.read_text(encoding="utf-8")
        if "superseded by gitos_role_brief.md" not in txt:
            legacy_pf_pointer.write_text(
                txt + "\n\n> NOTE: superseded by gitos_role_brief.md "
                      "(the project-flow skill was renamed to gitos).\n",
                encoding="utf-8")
            print("OK   annotated legacy project_flow_role_brief.md (superseded)")

    memory_index = memory_dir / "MEMORY.md"
    pointer_line = (
        f"- [{project_name} gitos role brief](gitos_role_brief.md) "
        f"— reloadable agent-system pointer; load on fresh session or post-compaction"
    )
    if not memory_index.exists():
        memory_index.write_text(f"# Memory index — {project_name}\n\n{pointer_line}\n",
                                encoding="utf-8")
        print(f"OK   wrote {memory_index.name}")
    elif "gitos_role_brief.md" not in memory_index.read_text(encoding="utf-8"):
        with memory_index.open("a", encoding="utf-8") as f:
            f.write("\n" + pointer_line + "\n")
        print("OK   appended pointer to MEMORY.md")
    else:
        print("SKIP pointer already in MEMORY.md")

    # ---- CLAUDE.md context anchor (sentinel-guarded, upserted) ------------
    # The durable recovery seed for the canary system (WO-028): the harness re-injects
    # CLAUDE.md into every context window, so the marker requirement + recovery trigger
    # survive here even when the skill directive washes out under compaction. Managed
    # block only — ensure_claude_section never touches content outside the markers, and
    # CREATES the file when absent so the backstop always exists.
    if not diagnostic_only:
        claude = root / "CLAUDE.md"
        section = render(read_template("CLAUDE-section.md.tmpl"), **tokens)
        status, carried = ensure_claude_section(claude, section)
        print({
            "created": "OK   wrote CLAUDE.md (gitos context anchor)",
            "updated": "OK   refreshed the gitos anchor block in CLAUDE.md",
            "preserved": "OK   refreshed the gitos anchor block in CLAUDE.md",
            "appended": "OK   appended the gitos anchor block to CLAUDE.md",
            "unchanged": "SKIP CLAUDE.md gitos anchor current",
        }[status])
        # Never silently delete: say what was found inside the managed block and kept.
        if carried:
            print(f"     PRESERVED {len(carried)} line(s) found inside the managed block that "
                  "the refresh did not account for:")
            for line in carried:
                print(f"       | {line}")
            print("     They were carried through, just inside the END marker. The block is "
                  "engine-managed —")
            print("     content you want to own permanently belongs OUTSIDE the markers "
                  "(see references/bridge.md).")

    # ---- ensure version control (WO-011) ----------------------------------
    # Reverses the old "offer, never run". `ensure` (default) auto-inits git when absent,
    # AFTER reporting intent (the false-negative backstop). `skip` opts out entirely;
    # `offer` keeps the legacy recommend-only behavior. Detection is robust (has_git).
    if args.git == "skip":
        pass  # opt-out: no git action
    elif args.git == "offer":
        if not has_git(root):
            print("\nGIT  no git repository detected. The pipeline + brain are an audit trail")
            print("     and are only durable under version control. Recommended (ask the user first):")
            print(f"       cd {posix_root} && git init")
            print(f"     Track the pipeline home; a .gitignore should NOT ignore '{home_label}/'.")
    else:  # ensure (default)
        if has_git(root):
            print("\nGIT  already under version control (.git present, or inside a parent "
                  "work-tree) — no init needed.")
        else:
            # Report BEFORE any git runs, so a false-negative ("a repo I missed") is visible.
            print(f"\nGIT  no git repository detected at {posix_root}.")
            print("     ENSURE: initializing one now so the pipeline home + brain (the audit")
            print("     trail) are durable under version control. If a repo already exists here")
            print("     or in a parent dir I missed, stop and re-run with --git skip.")
            if git_init(root):
                print("OK   ran: git init")
                gi, ga = root / ".gitignore", root / ".gitattributes"
                report(write_if_missing(gi, starter_gitignore(home_label, args.brain == "on")),
                       gi, root)
                report(write_if_missing(ga, STARTER_GITATTRIBUTES), ga, root)
                print("     Starter .gitignore/.gitattributes laid. The baseline COMMIT is the")
                print("     inception agent's next step (scaffold lays files; it never commits).")

    print("\nScaffolding complete. Next steps (see references/roles/inception.md):")
    print(f"  1. Fill {home_label}/HANDOFF.md from the interview.")
    if args.brain == "on" and not diagnostic_only:
        print(f"  2. Seed {home_label}/brain/ at the chosen ingest depth (minimal/moderate/aggressive).")
    print("  3. Hand control to the orchestrator (references/roles/orchestrator.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
