"""brain_lint — deterministic health / redundancy detector for a GitOS brain.

Read-only. Scans a brain's `wiki/` and reports, by class, the structural problems
that the orchestrator's reflection pass tends to miss:

  - duplicate / near-duplicate pages   (same slug-stem, or high title + wikilink overlap)
  - orphans                            (no inbound [[links]] and not listed in index.md)
  - stale                              (frontmatter `updated:` older than --stale-days)
  - broken wikilinks                   ([[target]] with no matching page)
  - cross-layer redundancy             (page restates a work-order, or mirrors code)

It never edits anything. The orchestrator acts on the report: small fixes inline in
the reconcile pass, large restructures as a consolidation work-order in the INDEX.

Usage:
    python brain_lint.py <BRAIN_DIR> [--stale-days N] [--json]

<BRAIN_DIR> is the brain root (the directory containing `wiki/`), e.g.
`<repo>/.gitos/brain`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

PAGE_TYPES = ("sources", "entities", "concepts", "decisions")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
WORKORDER = re.compile(r"\b(?:WO-\d+|bug_\d{2,})\b", re.IGNORECASE)
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
    )


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


def lint(brain_dir: Path, stale_days: int, today: date) -> dict:
    wiki = brain_dir / "wiki"
    pages: list[Page] = []
    for ptype in PAGE_TYPES:
        d = wiki / ptype
        if d.is_dir():
            for f in sorted(d.glob("*.md")):
                pages.append(parse_page(f, ptype))

    # known page identifiers (slug + title-slug) -> page
    known: dict[str, Page] = {}
    for p in pages:
        known.setdefault(p.slug, p)
        known.setdefault(p.title_slug, p)

    index_text = ""
    idx = wiki / "index.md"
    if idx.exists():
        index_text = idx.read_text(encoding="utf-8", errors="replace").lower()

    inbound: dict[str, int] = {p.slug: 0 for p in pages}
    broken: list[dict] = []
    for p in pages:
        for tgt in p.wikilinks:
            hit = known.get(tgt)
            if hit is None:
                broken.append({"page": str(p.path), "broken_link": tgt})
            elif hit.slug != p.slug:
                inbound[hit.slug] = inbound.get(hit.slug, 0) + 1

    orphans, stale, cross_layer = [], [], []
    for p in pages:
        listed = (p.slug in index_text) or (p.title_slug in index_text)
        if inbound.get(p.slug, 0) == 0 and not listed:
            orphans.append({"page": str(p.path)})
        if p.updated and (today - p.updated).days > stale_days:
            stale.append({"page": str(p.path), "updated": p.updated.isoformat(),
                          "age_days": (today - p.updated).days})
        # cross-layer: restates a work-order (in body, not the legit frontmatter field)
        wo_hits = len(WORKORDER.findall(p.body))
        if wo_hits >= 2 and not p.fm_work_order:
            cross_layer.append({"page": str(p.path), "reason": f"restates work-order(s) x{wo_hits}"})
        elif wo_hits >= 3:
            cross_layer.append({"page": str(p.path), "reason": f"work-order id appears x{wo_hits} in body"})
        cr = code_ratio(p.body)
        if cr > 0.5 and len([ln for ln in p.body.splitlines() if ln.strip()]) > 15:
            cross_layer.append({"page": str(p.path),
                                "reason": f"body is {cr:.0%} code — mirrors code instead of mapping it"})

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

    return {
        "brain_dir": str(brain_dir),
        "page_count": len(pages),
        "duplicates": dups,
        "orphans": orphans,
        "stale": stale,
        "broken_wikilinks": broken,
        "cross_layer_redundancy": cross_layer,
    }


def print_report(r: dict) -> None:
    print(f"brain_lint - {r['brain_dir']}  ({r['page_count']} pages)\n")
    sections = [
        ("Duplicate / near-duplicate pages", "duplicates"),
        ("Orphans (no inbound links, not in index)", "orphans"),
        ("Stale pages", "stale"),
        ("Broken wikilinks", "broken_wikilinks"),
        ("Cross-layer redundancy", "cross_layer_redundancy"),
    ]
    total = 0
    for title, key in sections:
        items = r[key]
        total += len(items)
        flag = "OK" if not items else "!!"
        print(f"[{flag}] {title}: {len(items)}")
        for it in items:
            print(f"       - {json.dumps(it, ensure_ascii=False)}")
    print(f"\n{'CLEAN - nothing flagged.' if total == 0 else f'{total} item(s) flagged. Fix small ones inline; large restructures -> a consolidation work-order in INDEX.md.'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only brain health/redundancy detector.")
    ap.add_argument("brain_dir")
    ap.add_argument("--stale-days", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    brain_dir = Path(args.brain_dir).resolve()
    if not (brain_dir / "wiki").is_dir():
        print(f"ERROR: no wiki/ under {brain_dir} (is this a brain dir?)", file=sys.stderr)
        return 1

    r = lint(brain_dir, args.stale_days, date.today())
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print_report(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
