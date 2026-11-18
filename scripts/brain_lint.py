"""brain_lint — deterministic health / redundancy detector for a GitOS brain.

Scans a brain's `wiki/` and reports, by class, the structural problems that the
orchestrator's reflection pass tends to miss:

  - duplicate / near-duplicate pages   (same slug-stem, or high title + wikilink overlap)
  - stale                              (an active page whose `updated:` is older than
                                        --stale-days; a `rests_on` path or commit that no
                                        longer exists; a `superseded_by` that does not
                                        resolve. Record-dated pages are exempt from the
                                        AGE test, and the exemption is counted and reported,
                                        never silent)
  - broken wikilinks                   ([[target]] with no matching page)
  - cross-layer redundancy             (page restates a work-order, or mirrors code)
  - schema                             (front matter: type, description, status, updated)
  - index                              (wiki/index.md over its cap, or not the generated one)

The front matter is the source of truth and `wiki/index.md` is generated from it:
`--write-index` rebuilds it (one line per active page, grouped by type, superseded pages
left out; capped at 200 lines / 8 KB), `--check` exits 1 when the schema or the index
is off. Without either flag it only reports and never edits anything. The orchestrator
acts on the report: small fixes inline, large restructures as a consolidation work-order.

Usage:
    python brain_lint.py <BRAIN_DIR> [--stale-days N] [--root DIR] [--json]
                         [--write-index | --check]

<BRAIN_DIR> is the brain root (the directory containing `wiki/`), e.g.
`<repo>/.gitos/brain`. `--root` is the repo root that `rests_on` paths resolve against
(default: two levels above the brain).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

PAGE_TYPES = ("sources", "entities", "concepts", "decisions")
# The front-matter `type` each directory holds, and the heading its index group carries.
TYPE_OF = {"sources": "source", "entities": "entity", "concepts": "concept", "decisions": "decision"}
GROUP_TITLE = {"sources": "Sources", "entities": "Entities", "concepts": "Concepts", "decisions": "Decisions"}
STATUSES = ("active", "superseded")
# The index is read at the start of every session, so it is capped. A line is `[[slug]] — description`;
# DESCRIPTION_MAX keeps one entry short enough that the cap holds for a brain of a hundred pages.
INDEX_MAX_LINES = 200
INDEX_MAX_BYTES = 8 * 1024
DESCRIPTION_MAX = 140
DEFAULT_STALE_DAYS = 90
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
# Page types whose date is a RECORD, not a freshness claim. A decision record's `updated:`
# is the date the decision was made — it cannot be renewed without asserting that a past
# decision was re-made today, so flagging one as stale demands the single remedy the engine
# forbids (writing a false date) and can never be cleared truthfully.
#
# Exempt from the STALE check ONLY: duplicates, orphans, broken wikilinks and cross-layer
# redundancy still apply — a decision record can absolutely carry a rotted link. Any page of
# any type opts out the same way with `historical: true` in frontmatter (a page transcribing
# a fixed source, say, whose date records a transcription rather than a freshness claim).
#
# Exemptions are COUNTED and surfaced in the report: a check that silently skips pages claims
# a health it did not verify.
RECORD_DATED_PTYPES = ("decisions",)
FM_TRUE = {"true", "yes", "1"}
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
WORKORDER = re.compile(r"\b(?:WO-\d+|bug_\d{2,})\b", re.IGNORECASE)
# A markdown link to an order (`[WO-164](work-orders/WO-164/order.md)`) is a pointer, not a
# restatement: the whole link, text and target, is dropped before ids are counted. What is left
# is prose, where DISTINCT ids are counted, so one order named several times is one order.
MD_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")


def wo_ids(body: str) -> set[str]:
    return {m.upper() for m in WORKORDER.findall(MD_LINK.sub(" ", body))}


FENCE = re.compile(r"^\s*```")
STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "for", "in", "on", "is",
             "page", "the-", "with", "this", "that", "by"}


def slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.strip().lower())).strip("-")


def title_tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOPWORDS and len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Page:
    path: Path
    ptype: str
    slug: str           # filename stem
    title: str
    title_slug: str
    updated: date | None
    wikilinks: set[str] = field(default_factory=set)   # slugified targets
    body: str = ""
    fm_work_order: bool = False
    fm_historical: bool = False   # `historical: true` -> opt out of the stale check
    fm: dict = field(default_factory=dict)   # the raw front matter (first-colon split)


def parse_page(path: Path, ptype: str) -> Page:
    raw = path.read_text(encoding="utf-8", errors="replace")
    fm, body = {}, raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            block = raw[3:end]
            body = raw[end + 4:]
            for line in block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip()
    updated = None
    for key in ("updated", "created", "decided"):
        val = fm.get(key, "")
        m = re.search(r"\d{4}-\d{2}-\d{2}", val)
        if m:
            try:
                updated = datetime.strptime(m.group(0), "%Y-%m-%d").date()
                if key == "updated":
                    break
            except ValueError:
                pass
    mtitle = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    title = (mtitle.group(1).strip() if mtitle else path.stem)
    links = {slugify(t.split("|")[0]) for t in WIKILINK.findall(body)}
    return Page(
        path=path, ptype=ptype, slug=path.stem, title=title, title_slug=slugify(title),
        updated=updated, wikilinks=links, body=body,
        fm_work_order=bool(fm.get("work_order")),
        fm_historical=fm.get("historical", "").strip().strip("\"'").lower() in FM_TRUE,
        fm=fm,
    )


def fm_list(value: str) -> list[str]:
    """A one-line front-matter list (`[a, b]` or `a, b`) -> its entries, quotes stripped."""
    v = value.strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [x.strip().strip("\"'") for x in v.split(",") if x.strip().strip("\"'")]


def link_target(value: str) -> str:
    """`[[Some Page]]`, `[[slug|alias]]` or a bare slug -> the slug it names."""
    v = value.strip().strip("\"'")
    m = WIKILINK.search(v)
    return slugify((m.group(1) if m else v).split("|")[0])


def commit_exists(root: Path, sha: str) -> bool | None:
    """True / False when git can answer, None when it cannot (no git, or `root` is not a repo)."""
    try:
        cp = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"],
                            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode == 0:
        return True
    probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-dir"], capture_output=True, text=True)
    return False if probe.returncode == 0 else None


def check_schema(pages: list) -> list[dict]:
    """Front-matter schema: `type` (matching the directory), `description` (one line, capped),
    `status` (active / superseded), `superseded_by` (when superseded) and a dated `updated`."""
    out: list[dict] = []
    for p in pages:
        bad: list[str] = []
        t = p.fm.get("type", "").strip()
        if t != TYPE_OF[p.ptype]:
            bad.append(f"type is {t!r}, expected {TYPE_OF[p.ptype]!r}")
        d = p.fm.get("description", "").strip().strip("\"'")
        if not d:
            bad.append("no description (one line: when to read this page)")
        elif len(d) > DESCRIPTION_MAX:
            bad.append(f"description is {len(d)} chars, over {DESCRIPTION_MAX}")
        st = p.fm.get("status", "").strip()
        if st not in STATUSES:
            bad.append(f"status is {st!r}, expected one of {', '.join(STATUSES)}")
        if st == "superseded" and not p.fm.get("superseded_by", "").strip():
            bad.append("status superseded without superseded_by")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.fm.get("updated", "").strip()):
            bad.append("updated is not a YYYY-MM-DD date")
        if bad:
            out.append({"page": str(p.path), "problems": bad})
    return out


def build_index(pages: list) -> str:
    """The generated `wiki/index.md`: one `[[slug]] — description` line per active page, grouped by
    type, superseded pages left out. Deterministic (no date), so a drift check can compare bytes."""
    lines = ["# Brain index", "",
             "Generated by `brain_lint.py --write-index` from each page's front matter: edit a page's "
             "`description`, then regenerate. One line per active page; superseded pages are left out.", ""]
    n = 0
    for ptype in PAGE_TYPES:
        group = sorted((p for p in pages if p.ptype == ptype and p.fm.get("status", "active").strip() != "superseded"),
                       key=lambda p: p.slug)
        if not group:
            continue
        lines += [f"## {GROUP_TITLE[ptype]}", ""]
        for p in group:
            d = " ".join(p.fm.get("description", "").strip().strip("\"'").split()) or "(no description)"
            lines.append(f"- [[{p.slug}]] — {d}")
            n += 1
        lines.append("")
    if n == 0:
        lines += ["No pages yet.", ""]
    return "\n".join(lines)


def index_size_findings(text: str, pages: list) -> list[dict]:
    """Over the cap -> one finding that names the longest descriptions (what to shorten)."""
    nbytes, nlines = len(text.encode("utf-8")), text.count("\n")
    if nbytes <= INDEX_MAX_BYTES and nlines <= INDEX_MAX_LINES:
        return []
    longest = sorted(((len(p.fm.get("description", "")), p.slug) for p in pages
                      if p.fm.get("status", "active").strip() != "superseded"), reverse=True)[:5]
    return [{"problem": f"index is {nbytes} bytes / {nlines} lines, cap {INDEX_MAX_BYTES} / {INDEX_MAX_LINES}",
             "longest_descriptions": [f"{slug} ({n} chars)" for n, slug in longest]}]


def load_pages(wiki: Path) -> list:
    pages = []
    for ptype in PAGE_TYPES:
        d = wiki / ptype
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                pages.append(parse_page(f, ptype))
    return pages


def write_index(brain_dir: Path) -> tuple[Path, str, list[dict]]:
    """Regenerate `wiki/index.md` (LF) -> (path, text, size findings)."""
    wiki = brain_dir / "wiki"
    pages = load_pages(wiki)
    text = build_index(pages)
    path = wiki / "index.md"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path, text, index_size_findings(text, pages)


def code_ratio(body: str) -> float:
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return 0.0
    in_fence, code = False, 0
    for ln in body.splitlines():
        if FENCE.match(ln):
            in_fence = not in_fence
            code += 1
            continue
        if in_fence and ln.strip():
            code += 1
    return code / max(1, len(lines))


def lint(brain_dir: Path, stale_days: int, today: date, root: Path | None = None) -> dict:
    wiki = brain_dir / "wiki"
    root = Path(root) if root else brain_dir.parent.parent
    pages: list[Page] = load_pages(wiki)

    # known page identifiers (slug + title-slug) -> page
    known: dict[str, Page] = {}
    for p in pages:
        known.setdefault(p.slug, p)
        known.setdefault(p.title_slug, p)

    broken: list[dict] = []
    for p in pages:
        for tgt in p.wikilinks:
            if known.get(tgt) is None:
                broken.append({"page": str(p.path), "broken_link": tgt})

    stale, cross_layer = [], []
    stale_exempt = 0
    commits_unchecked = 0
    for p in pages:
        superseded = p.fm.get("status", "").strip() == "superseded"
        if p.updated and not superseded and (today - p.updated).days > stale_days:
            # Counted only when the exemption actually SUPPRESSED a finding, so the reported
            # number is the size of what was withheld from this run - not a census of how many
            # exempt pages happen to exist.
            if p.ptype in RECORD_DATED_PTYPES or p.fm_historical:
                stale_exempt += 1
            else:
                stale.append({"page": str(p.path), "reason": f"updated more than {stale_days} days ago",
                              "updated": p.updated.isoformat(), "age_days": (today - p.updated).days})
        # `rests_on`: the paths or commits the page depends on must still exist.
        for ref in fm_list(p.fm.get("rests_on", "")):
            if COMMIT.match(ref):
                ok = commit_exists(root, ref)
                if ok is None:
                    commits_unchecked += 1
                elif not ok:
                    stale.append({"page": str(p.path), "reason": f"rests_on commit {ref} does not exist"})
            elif not (root / ref.split("#")[0]).exists():
                stale.append({"page": str(p.path), "reason": f"rests_on path {ref} does not exist"})
        # `superseded_by` must name a page.
        sb = p.fm.get("superseded_by", "").strip()
        if sb and known.get(link_target(sb)) is None:
            stale.append({"page": str(p.path), "reason": f"superseded_by {sb} does not resolve to a page"})
        # cross-layer: restates a work-order (in body, not the legit frontmatter field)
        wo_hits = len(wo_ids(p.body))
        if wo_hits >= 2 and not p.fm_work_order:
            cross_layer.append({"page": str(p.path), "reason": f"restates work-order(s) x{wo_hits}"})
        elif wo_hits >= 3:
            cross_layer.append({"page": str(p.path), "reason": f"work-order id appears x{wo_hits} in body"})
        cr = code_ratio(p.body)
        if cr > 0.5 and len([ln for ln in p.body.splitlines() if ln.strip()]) > 15:
            cross_layer.append({"page": str(p.path),
                                "reason": f"body is {cr:.0%} code - mirrors code instead of mapping it"})

    # duplicate / near-duplicate
    dups: list[dict] = []
    stems: dict[str, list[Page]] = {}
    for p in pages:
        stems.setdefault(p.slug, []).append(p)
    for slug, group in stems.items():
        if len(group) > 1:
            dups.append({"kind": "same-slug", "slug": slug,
                         "pages": [str(g.path) for g in group]})
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            a, b = pages[i], pages[j]
            if a.slug == b.slug:
                continue
            tj = jaccard(title_tokens(a.title), title_tokens(b.title))
            shared = len(a.wikilinks & b.wikilinks)
            identical_links = bool(a.wikilinks) and a.wikilinks == b.wikilinks
            if tj >= 0.6 or (tj >= 0.4 and shared >= 3) or (identical_links and shared >= 2 and tj >= 0.3):
                dups.append({"kind": "near-duplicate",
                             "pages": [str(a.path), str(b.path)],
                             "title_jaccard": round(tj, 2), "shared_links": shared})

    # the generated index: capped, and the committed file must be the generated one
    generated = build_index(pages)
    index = index_size_findings(generated, pages)
    idx = wiki / "index.md"
    committed = idx.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n") if idx.exists() else None
    if committed is None:
        index.append({"problem": "wiki/index.md is missing: run `brain_lint.py <brain> --write-index`"})
    elif committed != generated:
        index += index_size_findings(committed, pages)
        index.append({"problem": "wiki/index.md is not the generated index: run "
                                 "`brain_lint.py <brain> --write-index` (never edit it by hand)"})

    return {
        "brain_dir": str(brain_dir),
        "page_count": len(pages),
        "duplicates": dups,
        "stale": stale,
        "stale_exempt": stale_exempt,
        "commits_unchecked": commits_unchecked,
        "broken_wikilinks": broken,
        "cross_layer_redundancy": cross_layer,
        "schema": check_schema(pages),
        "index": index,
    }


def print_report(r: dict) -> None:
    print(f"brain_lint - {r['brain_dir']}  ({r['page_count']} pages)\n")
    sections = [
        ("Duplicate / near-duplicate pages", "duplicates"),
        ("Stale pages (age, rests_on, superseded_by)", "stale"),
        ("Broken wikilinks", "broken_wikilinks"),
        ("Cross-layer redundancy", "cross_layer_redundancy"),
        ("Front-matter schema", "schema"),
        ("Generated index (cap, drift)", "index"),
    ]
    total = 0
    for title, key in sections:
        items = r[key]
        total += len(items)
        flag = "OK" if not items else "!!"
        # No false CLEAN: when a check held pages back or could not run, its own line says how many.
        # An unreported exemption would read as a health this run never actually verified.
        suffix = ""
        if key == "stale":
            if r.get("stale_exempt", 0):
                suffix += f" ({r['stale_exempt']} exempt from the age test: record-dated)"
            if r.get("commits_unchecked", 0):
                suffix += f" ({r['commits_unchecked']} rests_on commit(s) not checked: no git)"
        print(f"[{flag}] {title}: {len(items)}{suffix}")
        for it in items:
            print(f"       - {json.dumps(it, ensure_ascii=False)}")
    print(f"\n{'CLEAN - nothing flagged.' if total == 0 else f'{total} item(s) flagged. Fix small ones inline; large restructures -> a consolidation work-order in INDEX.md.'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Brain health/redundancy detector and index generator.")
    ap.add_argument("brain_dir")
    ap.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    ap.add_argument("--root", default=None, help="repo root that `rests_on` paths resolve against")
    ap.add_argument("--json", action="store_true")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write-index", action="store_true",
                      help="regenerate wiki/index.md from the front matter (exit 1 when it is over its cap)")
    mode.add_argument("--check", action="store_true",
                      help="exit 1 when the front-matter schema or the generated index is off")
    args = ap.parse_args()

    brain_dir = Path(args.brain_dir).resolve()
    if not (brain_dir / "wiki").is_dir():
        print(f"ERROR: no wiki/ under {brain_dir} (is this a brain dir?)", file=sys.stderr)
        return 1

    if args.write_index:
        path, text, over = write_index(brain_dir)
        print(f"OK   wrote {path} ({len(text.encode('utf-8'))} bytes, {text.count(chr(10))} lines)")
        for f in over:
            print(f"ERROR: {json.dumps(f, ensure_ascii=False)}", file=sys.stderr)
        return 1 if over else 0

    root = Path(args.root).resolve() if args.root else None
    r = lint(brain_dir, args.stale_days, date.today(), root)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print_report(r)
    if args.check and (r["schema"] or r["index"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
