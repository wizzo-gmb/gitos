"""canary — deterministic state canary for a GitOS home (the drift layer no other watcher covers).

Read-only. stdlib-only. No judgment calls. brain_lint watches the brain, selftest the
payload, path_guard the publish; the canary watches the HOME STATE layer none of them
cover:

  - ledger <-> files        (INDEX open/resolved rows vs work-orders/ + resolved/ files,
                             duplicate NNNs, orphaned WO files, nonconforming *.md filenames)
  - brainmeta counts        (.brainmeta.json counts.* vs on-disk wiki page counts;
                             unknown counts.* keys and rogue wiki/ page dirs)
  - engine-version stamp    (a stamp AHEAD of the installed skill VERSION = impossible state)
  - lens registries         (both layers: registry rows <-> lens files, name = filename,
                             required frontmatter keys, applies-to list-form)
  - link rot                (relative markdown links in INDEX.md + open WO files resolve)
  - brain delegation        (if a brain exists, run brain_lint and fold its findings in)
  - durable anchor          (repo-root CLAUDE.md carries the gitos block — the canary's own
                             recovery seed; missing/stale block is a finding, no CLAUDE.md a skip)
  - engine tool copies      (<home>/tools/<t>.py byte-compared against the skill's scripts/<t>.py;
                             a home copy that DIFFERS is reported — never refreshed here)

Graceful no-ops: empty home / no brain / no lenses -> that check is SKIPPED and reported as
skipped (its own [--] line per sub-check) — never silently CLEAN. A parse failure is a
finding, never a skip (no false-CLEAN). A NONEXISTENT <HOME> is a usage error (exit 2,
message on stderr) — the resolution gate must never read a missing home as green.
The canary reports and gates resolution; it never edits — fixing a finding is normal
orchestrator/implementer work.

Usage:
    python canary.py <HOME> [--skill-dir DIR] [--stale-days N] [--json]

<HOME> is the gitos home dir, e.g. `<repo>/.gitos`.
Exit codes: 0 = CLEAN (or nothing to check), 1 = findings, 2 = usage error.
(Deliberate divergence from brain_lint, which exits 0 with findings: the orchestrator's
resolution gate — no work-order resolved while the canary is red — needs 0/1 semantics.)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from importlib import util as importlib_util
from pathlib import Path
from urllib.parse import unquote

PAGE_TYPES = ("sources", "entities", "concepts", "decisions")   # brain_lint's constant
CATEGORIES = ("ledger", "counts", "stamp", "lenses", "links", "brain", "anchor", "tool")
# The engine's home tool copies (WO-034). <home>/tools/ holds byte-copies of the engine's own
# scripts — engine artifacts, a cache of the installed skill that the briefs invoke by home
# path. `upgrade` refreshes them (references/upgrade.md step 4); this category is what NOTICES
# when it didn't.
#
# THE SET IS DERIVED, NOT ENUMERATED (WO-029/031/033, the fourth time): the engine's home tools
# are the names present in BOTH <home>/tools/ and <skill>/scripts/. Neither side alone is the
# rule — <skill>/scripts/ alone would demand scaffold.py in every home (it is never copied
# there), and <home>/tools/ alone would claim every repo-local tool an operator ever parked in
# the dir. The INTERSECTION is exactly "an engine script this home carries a copy of", which is
# the set upgrade's rule already governs ("each tool the engine ships into <home>/tools/") and
# the set scaffold already lays. A future tool the engine lays there is covered on the day it
# ships, with no edit here and no engine release for the repo that meets it first.
#
# ONLY <home>/tools/ IS EVER READ. `<home>/agents/` is OPERATOR CONTENT, not an engine artifact
# — the v12/v13 boundary, re-pinned by WO-032. It is not reachable from this check by
# construction: the dir is never named here. Blurring the two categories is the failure that
# destroys operator data.
#
# A tool ABSENT from <home>/tools/ is NOT a finding: SKILL.md's fallback runs the skill's own
# current copy, so a home without a copy cannot be stale — those repos were never victims. This
# category is about a copy that EXISTS and has drifted; delivering a missing one is upgrade's job.
TOOL_SRC_DIR = "scripts"      # where the skill keeps the originals
TOOL_HOME_DIR = "tools"       # where a home keeps its copies (NEVER `agents/` — operator content)


def same_tool(a: bytes, b: bytes) -> bool:
    """Two copies are THE SAME TOOL if they differ only in how a checkout wrote their newlines.

    NOT a byte-compare, and the distinction is the whole point. `sync_to_live` byte-compares
    because it is a MIRROR — byte-identity IS its contract. This check asks a different question
    ("is the home carrying the same tool the skill ships?"), and a line ending is how git wrote
    the file out, not part of the tool. The same primitive serving two contracts needs two
    normalizations; using the mirror's predicate here was the bug.

    WHY IT MATTERS: `core.autocrlf=true` is the Git-for-Windows installer default (system scope),
    and `<home>/` is deliberately git-tracked. So a byte-compare reports every fresh Windows clone
    of a fully compliant repo as different — while `upgrade`, the correction it prints, rewrites
    the bytes, goes quiet, and lets the finding return on the next clone. A correction that does
    not correct is worse than no finding, and this category GATES.

    KNOWN LIMIT, stated rather than wished away: copies differing ONLY by a literal CRLF inside a
    string would compare equal. A tool source carrying raw CRLF bytes in a literal is pathological
    — every checkout it survives would mangle it anyway — and the cost is one missed finding, not
    a wrong one.
    """
    return a.replace(b"\r\n", b"\n") == b.replace(b"\r\n", b"\n")
# The durable context anchor (WO-028): the gitos managed block in repo-root CLAUDE.md,
# the canary's own recovery seed. The block must carry these tokens or it can't do its job.
CLAUDE_ANCHOR_START = "<!-- gitos:agent-system START -->"
CLAUDE_ANCHOR_END = "<!-- gitos:agent-system END -->"
ANCHOR_TOKENS = ("[gitos ·", "canary.py", "SKILL.md")   # marker + the two recovery pointers
# Ledger section headings are matched by PREFIX, not by literal equality: the tail is
# legitimate downstream variation — some ledgers carry a parenthetical tail ('(by severity)'),
# others a bare heading. The heading names the section; it is not a schema. (WO-029 class 3)
OPEN_HEADING = "## Open work-orders"
RESOLVED_HEADING = "## Resolved"
# --------------------------------------------------------------- the identity position
# The engine's ONE notion of where a work-order's identity lives. Both users below build on
# it — the FILENAME rule and the PROSE-ROW rule — so the two cannot drift apart (WO-033).
#
# EXACTLY three digits, closed by a non-digit — `wo_1234_x.md` must never quietly become
# WO-123. Stated once, here, so the two users below cannot disagree about it.
#
# Honest note on the (?!\d): today it is REDUNDANT in both users, and the code should say so
# rather than imply a guard it does not need. Each user already closes the NNN by other
# means — the filename rule requires a SEPARATOR immediately after it, and the prose rule a
# `\b`; neither can be followed by a fourth digit. It is kept as the explicit statement of
# the exactly-three intent at the one place both rules share, and it becomes load-bearing the
# moment either closer is relaxed. What actually defends the rule's precision is the widening
# that IS realistic — `\d{3,4}` — and gate 11 mutation-tests exactly that.
IDENT_NNN = r"(\d{3})(?!\d)"

# A work-order FILE is one whose name carries an NNN at the identity position: an optional
# letter prefix + separator, then the NNN, then a separator and a slug. This is a RULE, not
# an enumeration of forms. Enumeration is a strategy that fails once per novel downstream,
# and each failure costs that repo its resolution gate until the engine ships a fix — one
# error at three altitudes: one sample (WO-029), then three samples (WO-031), then three
# prefixes (v18). The rule ends the class instead of lowering its rate.
#
# THE DIRECTORY IS THE SCOPE. Files under `<home>/work-orders/` are work-orders by
# construction, so the filename does not have to prove it is one — it only has to yield an
# IDENTITY. The prefix therefore carries no meaning and is not inspected: `WO-007-x.md`,
# `wo_007_x.md`, `bug_007_x.md`, `task_007_x.md`, `WO007-x.md`, `007-x.md` and whatever the
# next repo invents all resolve. The engine's own form is one sample OF the rule, never the
# rule (this is the third work-order to say so; it is code now, not prose).
#
# The prefix is LETTERS ONLY on purpose: `[A-Za-z0-9]+` would let the regex backtrack a digit
# out of the prefix and read `wo1234_x.md` as WO-234 — manufacturing an identity out of a
# name that has none.
#
# Tolerance, never blindness: a name with NO resolvable identity is still reported
# (nonconforming-wo-filename) — `wo_1234_x.md` (four digits), `WO-1-x.md` (one), `notes.md`
# (none), `wo_029b_x.md` (a suffixed identity this ledger model cannot represent — reported
# rather than silently flattened onto its unsuffixed sibling).
#
# PINNED (WO-033) — the blindness risk, stated rather than wished away: a NON-work-order that
# does carry an identity (`notes_007_draft.md`) IS adopted as WO-007. No filename signal
# separates it from `task_007_real-work.md`, and a name-shaped heuristic to tell them apart
# would re-import the enumeration this rule removes. What is guaranteed is that adoption is
# never SILENT: with no INDEX row it surfaces as orphan-file; against a real WO-007 it
# surfaces as duplicate-file naming BOTH files. The cost is a finding with a different LABEL,
# never a missed one — and it is bounded by a directory that holds nothing but work-orders.
WO_FILE_RE = re.compile(rf"^(?:[A-Za-z]+[-_.]?)?{IDENT_NNN}[-_.][A-Za-z0-9][\w.-]*\.md$")
WO_FORM_NAMES = ("<prefix><sep>NNN<sep><slug>.md — an optional letter prefix (WO-, wo_, bug_, "
                 "task_, ... or none), then EXACTLY three digits, then a separator and a slug; "
                 "e.g. WO-007-thing.md, wo_007_thing.md, task_007_thing.md")
NNN_RE = re.compile(r"\d{3}")
EMDASH = "—"           # resolved rows may carry an em-dash NNN (no work-order number)
# A prose/blockquote ledger row's IDENTITY position: the NNN at the head of the item, past
# any blockquote/list markers and bold/code/link decoration, with an optional convention
# prefix. Anchored at the line head on purpose — an unanchored \d{3} scan would harvest every
# number in the prose ('240 findings') and manufacture phantom rows. (WO-029 class 3)
#
# Shares IDENT_NNN with the filename rule — one notion of "exactly three digits, closed"
# (WO-033). It deliberately does NOT share that rule's OPEN prefix, and the asymmetry is
# reasoned, not drift: a FILENAME is bounded by its directory (everything in the ledger dir is
# a work-order, so any prefix is fine), but a PROSE LINE is bounded by nothing — every
# sentence in the section is a candidate row. An open prefix here reads `**Fixed 240
# findings**` as row 240. The prefix stays enumerated precisely BECAUSE the line-head anchor
# is the only scope this rule has; the filename rule can drop its prefix precisely because it
# has a stronger scope than an anchor. Same identity core, different scope, hence different
# prefix policy — recorded so a future author does not "unify" them and reintroduce phantoms.
PROSE_NNN = re.compile(
    rf"^\s*(?:>+\s*)*(?:[-*+]\s+)?(?:\*\*|__|`|\[)*\s*(?:(?:WO|work|bug)[-_ ]?)?{IDENT_NNN}\b",
    re.IGNORECASE)
MDLINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
MDLINK_CELL = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
FENCE = re.compile(r"^\s*```")
SEP_CELL = re.compile(r"[-: ]*")
LENS_REQUIRED = ("name", "domain", "tags", "when-to-apply", "applies-to", "source")
# Provenance: operator-IMPORTED or orchestrator-AUTHORED (distilled). Requiring `imported:`
# of every lens forced a distilled lens to record FALSE provenance. Either key satisfies it;
# a lens with NEITHER is still reported. (WO-029 class 5)
LENS_PROVENANCE = ("imported", "authored")
BRAIN_LINT_KEYS = ("duplicates", "orphans", "stale", "broken_wikilinks", "cross_layer_redundancy")


# --------------------------------------------------------------------------- helpers
def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_frontmatter(raw: str) -> dict | None:
    """Minimal '---' frontmatter parser (brain_lint's idiom): first-colon split per line.
    Returns None when there is no frontmatter block (distinct from an empty one)."""
    if not raw.startswith("---"):
        return None
    end = raw.find("\n---", 3)
    if end == -1:
        return None
    fm: dict[str, str] = {}
    for line in raw[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def _table_rows(lines: list[str]) -> list[list[str]] | None:
    """Data rows of the first markdown table in `lines` (header + separator skipped,
    fenced code skipped). None when no table header line is present at all."""
    rows: list[list[str]] = []
    header_seen = in_fence = False
    for ln in lines:
        if FENCE.match(ln):
            in_fence = not in_fence
            continue
        s = ln.strip()
        if in_fence or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not header_seen:
            header_seen = True          # the header row itself
            continue
        if all(SEP_CELL.fullmatch(c) for c in cells):
            continue                    # the |---|---| separator row
        rows.append(cells)
    return rows if header_seen else None


def wo_nnn(name: str) -> str | None:
    """The NNN a work-order filename carries at the identity position, else None — under ANY
    ledger convention, including ones this engine has never seen (WO_FILE_RE is a rule, not a
    list of forms). One place decides what a work-order file is named — the ledger scan, the
    orphan scan and the link scan all key off this, so none of them can go blind on a naming
    convention, and a repo inventing a new one costs no engine release."""
    m = WO_FILE_RE.match(name)
    return m.group(1) if m else None


def section_lines(text: str, heading_prefix: str) -> list[str] | None:
    """Lines of the first '## ' section whose heading STARTS WITH `heading_prefix`. None
    when no such heading exists (callers report 'cannot parse' — never silently CLEAN).
    Prefix, not equality: the heading's tail is legitimate downstream variation."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith(heading_prefix):
            block: list[str] = []
            for nxt in lines[i + 1:]:
                if nxt.strip().startswith("## "):
                    break
                block.append(nxt)
            return block
    return None


def prose_row_nnns(block: list[str]) -> list[str]:
    """Line-head identity NNNs of a PROSE/blockquote ledger section: one per line that LEADS
    with an NNN at the identity position (see PROSE_NNN), fenced code skipped. This is the
    prose ROW signal — the `> 042 = ...` / `- 042: ...` blockquote/list entries a section
    carries as text.

    It deliberately does NOT harvest markdown-LINKED work-order files: a link to a work-order
    inside a table cell or a sentence is a CROSS-REFERENCE, not a row of THIS section. That
    link top-up (prose_nnns) belongs only to a section with no table of its own, where a row
    may be carried solely as a link; folding it into a table section would manufacture a
    phantom row out of every citation (WO-038). Fenced code is skipped so an EXAMPLE ledger
    row shown in a ``` block is never read as a real row. Duplicates are preserved — a real
    duplicate-NNN collision in prose must still be caught."""
    out: list[str] = []
    in_fence = False
    for ln in block:
        if FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = PROSE_NNN.match(ln)
        if m:
            out.append(m.group(1))
    return out


def prose_nnns(block: list[str]) -> list[str]:
    """Row NNNs of a PROSE/blockquote ledger section with NO table of its own — the fallback
    shape. Two deterministic signals, in order:

      1. each item's line-head IDENTITY-position NNN (prose_row_nnns);
      2. a top-up from work-order files LINKED in the section, for rows carried only as a
         markdown link.

    (2) contributes only NNNs (1) did not already see, so a row that both leads with its NNN
    and links its own file counts ONCE — one row, never a phantom duplicate. Duplicates
    WITHIN (1) are preserved: a real duplicate-NNN collision in a prose ledger must still be
    caught. Empty -> the caller reports cannot-parse (no false-CLEAN).

    The link top-up is EXCLUSIVE to a no-table section. A section that also has a table folds
    in only signal (1) via prose_row_nnns — see check_ledger — because in a table section a
    markdown link is a citation, not a row (WO-038)."""
    out = prose_row_nnns(block)
    seen = set(out)
    for tgt in extract_links("\n".join(block)):
        nnn = wo_nnn(Path(tgt).name)
        if nnn and nnn not in seen:
            seen.add(nnn)
            out.append(nnn)
    return out


def clean_cell(cell: str) -> str:
    return cell.strip().strip("`").strip("*").strip()


def lens_row_name(cell: str) -> str:
    """The lens name in a registry Lens cell: a bare stem OR a navigable markdown link
    `[name](name.md)` — the link TARGET's stem is the name, since that is what the row points
    at. Without this, a link cell double-reports ONE condition as BOTH registry-row-no-file
    and lens-file-no-row. (WO-029 class 4)"""
    s = clean_cell(cell)
    m = MDLINK_CELL.fullmatch(s)
    if not m:
        return s
    label, tgt = m.group(1), m.group(2)
    t = unquote(tgt.strip("<>").split("#", 1)[0].strip())
    if t.endswith(".md"):
        return clean_cell(Path(t).name[:-3])
    return clean_cell(label)


def extract_links(text: str) -> list[str]:
    """Relative markdown-link targets in `text` — fenced code, inline `code` spans,
    absolute paths, URLs, mailto: and pure #anchors skipped; #fragments stripped;
    %XX unquoted."""
    out: list[str] = []
    in_fence = False
    for ln in text.splitlines():
        if FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        ln = re.sub(r"`[^`]*`", "", ln)   # quoted link *syntax* is code, not a link
        for tgt in MDLINK.findall(ln):
            t = tgt.strip("<>").split("#", 1)[0]
            if not t or "://" in t or t.startswith("mailto:"):
                continue
            if t.startswith(("/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", t):
                continue
            out.append(unquote(t))
    return out


def _load_module(name: str, path: Path):
    """Import a module by path. Registered in sys.modules BEFORE exec so @dataclass with
    string annotations (PEP 563) resolves — brain_lint hits this on Python 3.10."""
    spec = importlib_util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    mod = importlib_util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def resolve_skill_dir(arg: str | None) -> Path | None:
    """--skill-dir wins; else the dir above this file (a dev/skill checkout), else the
    default install — each accepted only if it carries a VERSION file."""
    if arg:
        return Path(arg).resolve()
    for cand in (Path(__file__).resolve().parent.parent,
                 Path.home() / ".claude" / "skills" / "gitos"):
        if (cand / "VERSION").is_file():
            return cand
    return None


# --------------------------------------------------------------------------- checks
def _wo_files(d: Path) -> tuple[dict[str, list[str]], list[str]]:
    """-> ({NNN: [work-order names under any known convention]}, [nonconforming *.md names])."""
    by_nnn: dict[str, list[str]] = {}
    bad: list[str] = []
    if d.is_dir():
        for f in sorted(d.glob("*.md")):
            nnn = wo_nnn(f.name)
            if nnn:
                by_nnn.setdefault(nnn, []).append(f.name)
            else:
                bad.append(f.name)
    return by_nnn, bad


def check_ledger(home: Path) -> list[dict]:
    items: list[dict] = []
    wo_dir = home / "work-orders"
    on_root, bad_root = _wo_files(wo_dir)
    on_res, bad_res = _wo_files(wo_dir / "resolved")

    # every *.md in the ledger dirs yields an identity or is a finding — a name the identity
    # rule cannot read would otherwise be silently invisible to the orphan/link scans
    for where, bad in (("work-orders", bad_root), ("work-orders/resolved", bad_res)):
        for name in bad:
            items.append({"kind": "nonconforming-wo-filename", "file": f"{where}/{name}",
                          "finding": f"{where}/{name} carries no work-order identity at the "
                                     f"identity position ({WO_FORM_NAMES}) -> rename it to "
                                     "carry one or move it out of the ledger dirs"})

    idx_text = _read(home / "INDEX.md")
    if idx_text is None:
        if on_root or on_res:
            items.append({"kind": "index-missing",
                          "finding": "work-orders exist but INDEX.md is missing -> restore the ledger"})
        return items

    # Each section contributes the UNION of its table-row NNNs and its prose/blockquote row
    # NNNs (WO-038). A real section can be BOTH a summary/subsection table AND prose entries;
    # the engine used to read it as a table XOR a prose ledger (table-first), so the instant a
    # section carried any table — even a header-only or one-row table — its prose rows went
    # unparsed and every prose-tracked work-order phantom-orphaned. The prose ROW signal folded
    # into a table section is the LINE-HEAD identity only (prose_row_nnns) — never the
    # citation-link top-up (prose_nnns), which would turn every cross-reference link in a cell
    # into a phantom row. A section with NO table at all keeps the full prose fallback
    # (line-head rows + link-only rows), unchanged. Only a section that is neither a table nor
    # a recognizable prose ledger is cannot-parse. (WO-029 class 3; WO-038)
    #
    # UNION is the safe direction for orphans: adding NNNs to a section's tracked set can only
    # REMOVE orphan-file findings, never add one. A genuinely stray file (no table row AND no
    # prose row) is still absent from the union and MUST still orphan. It CAN newly surface a
    # rows->files finding (a prose row whose file is missing / sits in the wrong dir) — that is
    # a real finding the XOR was hiding, not a false positive.
    open_block = section_lines(idx_text, OPEN_HEADING)
    res_block = section_lines(idx_text, RESOLVED_HEADING)
    open_rows = _table_rows(open_block) if open_block is not None else None
    res_rows = _table_rows(res_block) if res_block is not None else None
    open_prose_rows = prose_row_nnns(open_block) if open_block is not None else []
    res_prose_rows = prose_row_nnns(res_block) if res_block is not None else []

    open_nnns: list[str] = []
    if open_rows is not None:
        for row in open_rows:
            nnn = clean_cell(row[0]) if row else ""
            if NNN_RE.fullmatch(nnn):
                open_nnns.append(nnn)
            else:
                items.append({"kind": "cannot-parse", "section": "open", "cell": nnn,
                              "finding": f"open row col-1 '{nnn}' is not a 3-digit NNN -> fix the row"})
        # fold in prose/blockquote rows the table did not already carry (dedup against the
        # TABLE set only — a prose-internal duplicate collision is preserved for the check below)
        seen_open = set(open_nnns)
        open_nnns += [n for n in open_prose_rows if n not in seen_open]
    else:
        open_prose = prose_nnns(open_block) if open_block is not None else []
        if open_prose:
            open_nnns = open_prose        # prose-only ledger — a legitimate shape
        else:
            items.append({"kind": "cannot-parse", "section": OPEN_HEADING,
                          "finding": f"no '{OPEN_HEADING}...' section with a table or a "
                                     "recognizable prose ledger -> not a recognizable ledger; "
                                     "fix INDEX.md"})

    res_nnns: list[str] = []
    if res_rows is not None:
        for row in res_rows:
            nnn = clean_cell(row[0]) if row else ""
            if NNN_RE.fullmatch(nnn):
                res_nnns.append(nnn)
            elif nnn != EMDASH:   # em-dash = legitimate numberless row (inception deliverable)
                items.append({"kind": "cannot-parse", "section": "resolved", "cell": nnn,
                              "finding": f"resolved row col-1 '{nnn}' is neither a 3-digit NNN "
                                         "nor an em-dash -> fix the row"})
        seen_res = set(res_nnns)
        res_nnns += [n for n in res_prose_rows if n not in seen_res]
    else:
        res_prose = prose_nnns(res_block) if res_block is not None else []
        if res_prose:
            res_nnns = res_prose          # prose-only ledger — a legitimate shape
        else:
            items.append({"kind": "cannot-parse", "section": RESOLVED_HEADING,
                          "finding": f"no '{RESOLVED_HEADING}...' section with a table or a "
                                     "recognizable prose ledger -> not a recognizable ledger; "
                                     "fix INDEX.md"})

    # duplicate NNNs — within a section, and across open/resolved
    for section, nnns in (("Open", open_nnns), ("Resolved", res_nnns)):
        for nnn, n in sorted(Counter(nnns).items()):
            if n > 1:
                items.append({"kind": "duplicate-nnn", "nnn": nnn,
                              "finding": f"NNN {nnn} appears {n}x in {section} -> keep exactly one row"})
    for nnn in sorted(set(open_nnns) & set(res_nnns)):
        items.append({"kind": "duplicate-nnn", "nnn": nnn,
                      "finding": f"NNN {nnn} appears in both Open and Resolved -> keep exactly one row"})

    # duplicate files — two WO-NNN-*.md sharing an NNN in one dir, or across dirs
    for where, files in (("work-orders", on_root), ("work-orders/resolved", on_res)):
        for nnn, names in sorted(files.items()):
            if len(names) > 1:
                items.append({"kind": "duplicate-file", "nnn": nnn, "files": names,
                              "finding": f"{len(names)} files share NNN {nnn} in {where}/ -> keep exactly one"})
    for nnn in sorted(set(on_root) & set(on_res)):
        items.append({"kind": "wo-in-both", "nnn": nnn,
                      "finding": f"WO-{nnn} present in both work-orders/ and resolved/ -> keep exactly one"})

    # rows -> files (per side, only when that side parsed — no cascades on cannot-parse).
    # "parsed" = a table OR a recognized prose ledger; a prose side is a real row set. A table
    # side that folded in prose rows is still parsed (open_rows is not None).
    open_parsed = open_rows is not None or bool(open_nnns)
    res_parsed = res_rows is not None or bool(res_nnns)
    if open_parsed:
        for nnn in open_nnns:
            if nnn in on_root:
                continue
            if nnn in on_res:
                items.append({"kind": "open-row-file-in-resolved", "nnn": nnn,
                              "finding": f"open row {nnn}'s file is in resolved/ -> "
                                         "mark the row Resolved (or restore the file)"})
            else:
                items.append({"kind": "open-row-missing-file", "nnn": nnn,
                              "finding": f"open row {nnn} has no work-order file for NNN {nnn} "
                                         "under work-orders/ -> restore the file or drop the row"})
    if res_parsed:
        for nnn in res_nnns:
            # a resolved row may legitimately have NO file (landed as commit/decision page)
            if nnn in on_root and nnn not in on_res:
                items.append({"kind": "resolved-row-file-in-root", "nnn": nnn,
                              "finding": f"resolved row {nnn}'s file is still in work-orders/ -> "
                                         "move it to resolved/"})

    # files -> rows (needs both row sets; suppressed if either side failed to parse)
    if open_rows is not None and res_rows is not None:
        known = set(open_nnns) | set(res_nnns)
        for where, files in (("work-orders", on_root), ("work-orders/resolved", on_res)):
            for nnn in sorted(set(files) - known):
                items.append({"kind": "orphan-file", "file": f"{where}/{files[nnn][0]}",
                              "finding": f"{where}/{files[nnn][0]} has no INDEX row -> "
                                         "add a row (or remove the stray file)"})
    return items


def check_brainmeta(home: Path, installed: int | None) -> tuple[list[dict], list[dict], str | None]:
    """-> (counts items, stamp items, stamp skip-reason | None-if-compared)."""
    counts_items: list[dict] = []
    stamp_items: list[dict] = []
    brain = home / "brain"
    wiki = brain / "wiki"

    # rogue page dirs: a wiki/ subdir holding .md pages outside PAGE_TYPES is invisible
    # to counts AND to brain_lint's page scan -> finding, never silent
    if wiki.is_dir():
        for d in sorted(p for p in wiki.iterdir() if p.is_dir()):
            if d.name not in PAGE_TYPES and any(d.glob("*.md")):
                counts_items.append({"kind": "unknown-page-type", "dir": d.name,
                                     "finding": f"wiki/{d.name}/ holds .md page(s) but is not a "
                                                f"known page type ({', '.join(PAGE_TYPES)}) -> "
                                                "relocate the pages or extend the schema"})

    raw = _read(brain / ".brainmeta.json")
    if raw is None:
        if wiki.is_dir():
            counts_items.append({"kind": "brainmeta-missing",
                                 "finding": "brain/wiki/ exists but .brainmeta.json is missing -> "
                                            "restore the stamp file"})
        return counts_items, stamp_items, "no .brainmeta.json"
    try:
        meta = json.loads(raw)
        if not isinstance(meta, dict):
            raise ValueError("top level is not an object")
    except ValueError as e:
        counts_items.append({"kind": "cannot-parse",
                             "finding": f".brainmeta.json is not valid JSON ({e}) -> repair it"})
        return counts_items, stamp_items, "brainmeta unparseable"

    counts = meta.get("counts")
    if not isinstance(counts, dict):
        counts_items.append({"kind": "counts-missing",
                             "finding": "brainmeta has no counts object -> add counts per page type"})
    else:
        for t in PAGE_TYPES:
            d = wiki / t
            actual = len(list(d.glob("*.md"))) if d.is_dir() else 0
            expected = counts.get(t)
            if expected is None:
                if actual:
                    counts_items.append({"kind": "count-missing-key", "key": t, "actual": actual,
                                         "finding": f"counts.{t} absent, files={actual} -> set {actual}"})
            elif not isinstance(expected, int) or isinstance(expected, bool):
                counts_items.append({"kind": "cannot-parse", "key": t,
                                     "finding": f"counts.{t}='{expected}' is not an integer -> set {actual}"})
            elif expected != actual:
                counts_items.append({"kind": "count-mismatch", "key": t,
                                     "expected": expected, "actual": actual,
                                     "finding": f"counts.{t}={expected}, files={actual} -> set {actual}"})
        for key in sorted(set(counts) - set(PAGE_TYPES)):
            counts_items.append({"kind": "unknown-page-type", "key": key,
                                 "finding": f"counts.{key} is not a known page type "
                                            f"({', '.join(PAGE_TYPES)}) -> remove the key "
                                            "or fix the type name"})

    ev = meta.get("engine_version")
    if ev is None:
        # legal older shape — profile repos stamp in CLAUDE.md/BRIDGE.md instead
        return counts_items, stamp_items, "no engine_version in brainmeta"
    if installed is None:
        return counts_items, stamp_items, "no installed VERSION to compare"
    if not isinstance(ev, int) or isinstance(ev, bool):
        stamp_items.append({"kind": "cannot-parse",
                            "finding": f"engine_version '{ev}' is not an integer -> "
                                       "stamp the installed version"})
    elif ev > installed:
        stamp_items.append({"kind": "stamp-ahead", "stamp": ev, "installed": installed,
                            "finding": f"engine_version={ev} ahead of installed skill VERSION={installed} "
                                       f"-> impossible state; re-stamp {installed} or update the skill install"})
    # ev <= installed -> OK (behind just means an upgrade is pending)
    return counts_items, stamp_items, None


def check_lens_layer(layer_dir: Path, layer: str) -> list[dict]:
    items: list[dict] = []
    files = sorted(p for p in layer_dir.glob("*.md") if p.name != "index.md")
    reg_text = _read(layer_dir / "index.md")

    row_names: list[str] = []
    if reg_text is None:
        if files:
            items.append({"kind": "registry-missing", "layer": layer,
                          "finding": f"{layer} agents/ has lens files but no index.md registry -> "
                                     "add the registry"})
    else:
        rows = _table_rows(reg_text.splitlines())
        if rows is None:
            if files:
                items.append({"kind": "cannot-parse", "layer": layer,
                              "finding": f"{layer} agents/index.md has no registry table -> "
                                         "add the | Lens | ... | table"})
        else:
            for row in rows:
                name = lens_row_name(row[0]) if row else ""
                if name:
                    row_names.append(name)
                else:
                    items.append({"kind": "cannot-parse", "layer": layer,
                                  "finding": f"{layer} registry row with an empty Lens cell -> fix the row"})
            for name, n in sorted(Counter(row_names).items()):
                if n > 1:
                    items.append({"kind": "duplicate-row", "layer": layer, "name": name,
                                  "finding": f"{layer} registry lists '{name}' {n}x -> keep exactly one row"})
            stems = {f.stem for f in files}
            for name in sorted(set(row_names) - stems):
                items.append({"kind": "registry-row-no-file", "layer": layer, "name": name,
                              "finding": f"{layer} registry row '{name}' has no {name}.md in agents/ -> "
                                         "remove the row or restore the file"})
            for stem in sorted(stems - set(row_names)):
                items.append({"kind": "lens-file-no-row", "layer": layer, "name": stem,
                              "finding": f"{layer} agents/{stem}.md has no registry row -> "
                                         "add its row to index.md"})

    for f in files:
        fm = parse_frontmatter(_read(f) or "")
        if fm is None:
            items.append({"kind": "no-frontmatter", "layer": layer, "file": f.name,
                          "finding": f"{layer} agents/{f.name} has no frontmatter -> "
                                     "add the lens frontmatter block"})
            continue
        missing = [k for k in LENS_REQUIRED if k not in fm]
        # provenance: either key satisfies it; NEITHER is still a finding (class 5)
        if not any(k in fm for k in LENS_PROVENANCE):
            missing.append(" or ".join(LENS_PROVENANCE))
        if missing:
            items.append({"kind": "missing-keys", "layer": layer, "file": f.name, "keys": missing,
                          "finding": f"{layer} agents/{f.name} missing frontmatter key(s): "
                                     f"{', '.join(missing)} -> add them"})
        name = fm.get("name")
        if name is not None and name != f.stem:
            items.append({"kind": "name-mismatch", "layer": layer, "file": f.name,
                          "finding": f"{layer} agents/{f.name}: name '{name}' != filename stem "
                                     f"'{f.stem}' -> set name: {f.stem}"})
        at = fm.get("applies-to")
        # list-form or the schema-legal bare 'any' (references/agent-import.md)
        if at is not None and at != "any" and not (at.startswith("[") and at.endswith("]")):
            items.append({"kind": "applies-to-scalar", "layer": layer, "file": f.name,
                          "finding": f"{layer} agents/{f.name}: applies-to '{at}' is scalar -> "
                                     f"use list form [{at}] (or 'any')"})
    return items


def check_links(home: Path) -> list[dict]:
    """Link rot in INDEX.md + open work-order files.

    A target is resolved against BOTH the containing file's dir AND the repo root, and is
    only reported when NEITHER resolves. CommonMark itself resolves relative to the
    containing file, so `src.parent` alone is markdown-correct — but this tool detects DRIFT,
    it does not lint markdown, and flagging a path that demonstrably EXISTS is a false
    positive against that purpose. Re-basing to the repo root ALONE would be equally wrong:
    it would break legitimate home-relative links. Try both; report only a target that exists
    nowhere — the true-positive (a link to nothing) is untouched. (WO-029 class 2)
    """
    items: list[dict] = []
    repo_root = home.parent
    sources: list[Path] = []
    if (home / "INDEX.md").is_file():
        sources.append(home / "INDEX.md")
    wo_dir = home / "work-orders"
    if wo_dir.is_dir():
        sources.extend(sorted(f for f in wo_dir.glob("*.md") if wo_nnn(f.name)))
    for src in sources:
        rel = src.relative_to(home).as_posix()
        for tgt in extract_links(_read(src) or ""):
            if (src.parent / tgt).exists() or (repo_root / tgt).exists():
                continue
            items.append({"kind": "dead-link", "file": rel, "link": tgt,
                          "finding": f"{rel} -> {tgt} resolves neither beside the file nor at "
                                     "the repo root -> fix the link or restore the target"})
    return items


def check_brain_delegate(home: Path, stale_days: int, today: date) -> list[dict]:
    items: list[dict] = []
    brain = home / "brain"
    if not (brain / "wiki").is_dir():
        items.append({"kind": "not-a-brain",
                      "finding": "brain/ exists but has no wiki/ -> not a brain; "
                                 "re-scaffold or remove"})
        return items
    lint_path = home / "tools" / "brain_lint.py"
    if not lint_path.is_file():
        lint_path = Path(__file__).resolve().parent / "brain_lint.py"
    if not lint_path.is_file():
        items.append({"kind": "brain-lint-missing",
                      "finding": "no brain_lint.py at <home>/tools/ or beside canary.py -> "
                                 "a brain without a reachable linter is unchecked; copy the tool"})
        return items
    prev_dwb = sys.dont_write_bytecode
    sys.dont_write_bytecode = True   # read-only contract: no __pycache__ under <home>/tools/
    try:
        bl = _load_module("_canary_brain_lint", lint_path)
        rep = bl.lint(brain, stale_days=stale_days, today=today)
    except Exception as e:  # delegation failure must surface, never pass silently
        items.append({"kind": "brain-lint-error",
                      "finding": f"brain_lint raised {type(e).__name__}: {e} -> "
                                 "fix the tool copy or the brain"})
        return items
    finally:
        sys.dont_write_bytecode = prev_dwb
    # fold the importable report lists — brain_lint's CLI exits 0 even when it flags
    for key in BRAIN_LINT_KEYS:
        found = rep.get(key, [])
        if found:
            items.append({"kind": f"brain-{key}", "count": len(found), "items": found,
                          "finding": f"brain_lint {key}: {len(found)} item(s) -> "
                                     "fix inline or open a consolidation work-order"})
    return items


def check_anchor(claude_path: Path) -> list[dict]:
    """The durable context anchor: the gitos managed block in repo-root CLAUDE.md must exist
    and carry the recovery seed (the marker + the re-read/canary pointers). Called only when
    CLAUDE.md exists (a wholly absent CLAUDE.md is a visible skip, not a finding — inception /
    upgrade own creating it)."""
    items: list[dict] = []
    text = _read(claude_path) or ""
    if CLAUDE_ANCHOR_START not in text or CLAUDE_ANCHOR_END not in text:
        items.append({"kind": "anchor-missing",
                      "finding": "CLAUDE.md has no gitos:agent-system block -> the durable "
                                 "context anchor (the canary's recovery seed) is absent; "
                                 "re-run scaffold.py or `/gitos upgrade` to restore it"})
        return items
    i = text.index(CLAUDE_ANCHOR_START)
    block = text[i:text.index(CLAUDE_ANCHOR_END, i)]
    missing = [t for t in ANCHOR_TOKENS if t not in block]
    if missing:
        items.append({"kind": "anchor-stale", "missing": missing,
                      "finding": f"CLAUDE.md gitos block is missing recovery-seed token(s) "
                                 f"{missing} -> refresh the block (scaffold.py / `/gitos upgrade`)"})
    return items


def check_tools(home: Path, skill_dir: Path | None) -> tuple[list[dict], str | None]:
    """The engine's home tool copies: <home>/tools/<t>.py vs <skill>/scripts/<t>.py.
    -> (items, skip-reason | None-if-compared).

    REPORTS, NEVER FIXES. Refreshing a stale copy is `upgrade`'s job (references/upgrade.md
    step 4). A canary that refreshed would be the same category error upgrade's rule was just
    corrected for: silently overwriting a copy an operator may have edited. This check's whole
    contribution is that the refresh stops depending on someone remembering.

    SAYS "DIFFERENT", NOT "WHY". The compare proves the copy is not the skill's; it cannot
    distinguish stale from hand-modified, and it does not guess. Both have the same correction
    (`upgrade` — which reports and refreshes, with the prior bytes recoverable from git), so
    naming a cause would add a claim without adding an action.

    COMPARES CONTENT, NOT BYTES (see same_tool). Line endings are a checkout artifact, not part
    of the tool: byte-comparing flags every fresh Windows clone of a compliant repo, and this
    category gates. Verified against the real fleet, not a fixture — normalizing silenced a
    line-endings-only copy while both genuinely-drifted copies stayed red.

    THE SELF-REFERENCE WRINKLE (WO-034, WO-028's shape): a STALE home canary cannot report its
    OWN staleness — a copy predating this check simply has no such check to run, and stays quiet
    about being old. A detector cannot detect its own absence. This is not solvable from inside
    (a bootstrap trick would only move the trust, not remove it) and it does not need to be: the
    LAYER ABOVE terminates it. `upgrade` delivers the checking canary (that is WO-032), and a
    home with no copy at all runs the skill's current one by SKILL.md's fallback. This category
    is what keeps the copy honest AFTERWARDS. Named here so the limit is a known property rather
    than a surprise.
    """
    items: list[dict] = []
    if skill_dir is None:
        return items, "no skill install found"
    src = skill_dir / TOOL_SRC_DIR
    if not src.is_dir():
        return items, f"no <skill>/{TOOL_SRC_DIR}/"
    home_tools = home / TOOL_HOME_DIR
    if not home_tools.is_dir():
        return items, f"no <home>/{TOOL_HOME_DIR}/"

    # DERIVED (see TOOL_SRC_DIR above): the engine tools this home carries copies of = the
    # names present on BOTH sides. Non-recursive *.py on purpose — __pycache__/ is not a tool.
    names = sorted({p.name for p in home_tools.glob("*.py")} &
                   {p.name for p in src.glob("*.py")})
    if not names:
        # Nothing to compare is NOT nothing to say: a home whose tools/ holds no engine script
        # is unchecked, and unchecked must look different from clean. (Tolerance, never blindness.)
        return items, f"no engine tool copies in <home>/{TOOL_HOME_DIR}/"

    for name in names:
        try:
            home_bytes = (home_tools / name).read_bytes()
            skill_bytes = (src / name).read_bytes()
        except OSError as e:
            # An unreadable copy is a FINDING, never a skip — a compare that could not run must
            # not read as a compare that passed.
            items.append({"kind": "cannot-read", "tool": name,
                          "finding": f"<home>/{TOOL_HOME_DIR}/{name} or the skill's copy could "
                                     f"not be read ({type(e).__name__}) -> fix permissions, then "
                                     "re-run; an unreadable tool copy cannot be verified"})
            continue
        if not same_tool(home_bytes, skill_bytes):
            items.append({"kind": "tool-stale", "tool": name,
                          "finding": f"<home>/{TOOL_HOME_DIR}/{name} differs in content from the "
                                     f"installed skill's copy ({TOOL_SRC_DIR}/{name}) -> run "
                                     f"`/gitos upgrade` to refresh it. Line endings are normalized "
                                     f"first, so this is a real difference, not a checkout "
                                     f"artifact. It proves DIFFERENT, not why: the copy is stale, "
                                     f"or hand-modified, and this check cannot tell which"})
    return items, None


# --------------------------------------------------------------------------- run + report
def run(home: Path, skill_dir: Path | None, today: date, stale_days: int = 60) -> dict:
    r: dict = {"home": str(home), "skill_dir": str(skill_dir) if skill_dir else None,
               "installed_version": None, "skipped": []}
    for k in CATEGORIES:
        r[k] = []
    checked: set[str] = set()

    def skip(check: str, reason: str) -> None:
        r["skipped"].append({"check": check, "reason": reason})

    if skill_dir is None:
        skip("stamp", "no skill install found")
        skip("lenses:global", "no skill install found")
    else:
        raw = _read(skill_dir / "VERSION")
        v = raw.strip() if raw else ""
        if v.isdigit():
            r["installed_version"] = int(v)
        else:
            r["stamp"].append({"kind": "cannot-parse",
                               "finding": f"no readable integer VERSION under {skill_dir} -> "
                                          "point --skill-dir at a skill install"})

    # ledger + link rot
    if (home / "INDEX.md").is_file() or (home / "work-orders").is_dir():
        r["ledger"].extend(check_ledger(home))
        r["links"].extend(check_links(home))
        checked.update(("ledger", "links"))
    else:
        skip("ledger", "no INDEX.md and no work-orders/")
        skip("links", "no INDEX.md and no work-orders/")

    # brainmeta counts + stamp; brain delegation
    brain = home / "brain"
    if (brain / ".brainmeta.json").is_file() or (brain / "wiki").is_dir():
        c_items, s_items, stamp_reason = check_brainmeta(home, r["installed_version"])
        r["counts"].extend(c_items)
        r["stamp"].extend(s_items)
        checked.add("counts")
        if stamp_reason is None:
            checked.add("stamp")
        else:
            skip("stamp", stamp_reason)
    else:
        skip("counts", "no brain")
        if skill_dir is not None:
            skip("stamp", "no brain")
    if brain.is_dir():
        r["brain"].extend(check_brain_delegate(home, stale_days, today))
        checked.add("brain")
    else:
        skip("brain", "no brain")

    # lens registries, both layers
    repo_agents = home / "agents"
    if repo_agents.is_dir():
        r["lenses"].extend(check_lens_layer(repo_agents, "repo"))
        checked.add("lenses")
    else:
        skip("lenses:repo", "no <home>/agents/")
    if skill_dir is not None:
        global_agents = skill_dir / "agents"
        if global_agents.is_dir():
            r["lenses"].extend(check_lens_layer(global_agents, "global"))
            checked.add("lenses")
        else:
            skip("lenses:global", "no <skill>/agents/")

    # durable context anchor: the gitos block in repo-root CLAUDE.md (home is <root>/.gitos,
    # so its parent is the repo root). A wholly absent CLAUDE.md is a VISIBLE skip — whether
    # a repo should carry one is inception/upgrade's concern, not a false-CLEAN here.
    claude = home.parent / "CLAUDE.md"
    if claude.is_file():
        r["anchor"].extend(check_anchor(claude))
        checked.add("anchor")
    else:
        skip("anchor", "no CLAUDE.md at repo root")

    # engine tool copies: the home's cache of the engine's own scripts vs the installed skill.
    # Reports only — refreshing is `upgrade`'s job (WO-032/WO-034). Reads <home>/tools/ and
    # <skill>/scripts/ and nothing else: `<home>/agents/` is operator content, not a tool.
    t_items, t_reason = check_tools(home, skill_dir)
    r["tool"].extend(t_items)
    if t_reason is None:
        checked.add("tool")
    else:
        skip("tool", t_reason)

    for k in CATEGORIES:      # a category with findings is by definition checked
        if r[k]:
            checked.add(k)
    r["checked"] = sorted(checked)
    r["total"] = sum(len(r[k]) for k in CATEGORIES)
    return r


def print_report(r: dict) -> None:
    v = r["installed_version"]
    suffix = f"(installed VERSION {v})" if v is not None else "(no skill install found)"
    print(f"canary - {r['home']}  {suffix}\n")
    sections = [
        ("Ledger <-> files (INDEX vs work-orders/)", "ledger"),
        ("Brainmeta counts vs disk", "counts"),
        ("Engine-version stamp", "stamp"),
        ("Lens registries (repo + global)", "lenses"),
        ("Link rot (INDEX + open WOs)", "links"),
        ("Brain (delegated brain_lint)", "brain"),
        ("Durable anchor (CLAUDE.md recovery seed)", "anchor"),
        ("Engine tool copies (<home>/tools/ vs skill)", "tool"),
    ]
    skips: dict[str, list[dict]] = {}
    for s in r["skipped"]:
        skips.setdefault(s["check"].split(":")[0], []).append(s)
    total = 0
    for title, key in sections:
        items = r[key]
        total += len(items)
        if key in r["checked"]:
            flag = "OK" if not items else "!!"
            print(f"[{flag}] {title}: {len(items)}")
            for it in items:
                print(f"       - {json.dumps(it, ensure_ascii=False)}")
        elif not skips.get(key):
            print(f"[--] {title}: skipped (not applicable)")
        # every skipped sub-check gets its OWN [--] line — a skip folded into an
        # [OK] line would render "didn't look" as "looked, found nothing"
        for s in skips.get(key, []):
            sub = s["check"].split(":", 1)
            label = f"{title} [{sub[1]}]" if len(sub) > 1 else title
            print(f"[--] {label}: skipped ({s['reason']})")
    print(f"\n{'CLEAN - nothing flagged.' if total == 0 else f'{total} item(s) flagged. The canary reports; fixes are normal orchestrator/implementer work - resolution stays gated while red.'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only state canary for a GitOS home.")
    ap.add_argument("home", help="the gitos home dir, e.g. <repo>/.gitos")
    ap.add_argument("--skill-dir", default=None,
                    help="installed skill root override (default: auto-resolve)")
    ap.add_argument("--stale-days", type=int, default=60,
                    help="forwarded to the delegated brain_lint pass")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows consoles default to cp1252
    except (AttributeError, OSError):
        pass

    home = Path(args.home).resolve()
    if not home.is_dir():
        # a missing/typo'd home is a USAGE error — the resolution gate must never read it as green
        print(f"canary: no gitos home at {home} -> pass the gitos home dir, e.g. <repo>/.gitos",
              file=sys.stderr)
        if args.json:
            print(json.dumps({"home": str(home), "error": "no such home"},
                             indent=2, ensure_ascii=False))
        return 2

    r = run(home, resolve_skill_dir(args.skill_dir), date.today(), args.stale_days)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print_report(r)
    return 0 if r["total"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
