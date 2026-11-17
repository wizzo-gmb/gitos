# Lenses — operator-imported steering

The router (`SKILL.md` → *Lenses*) keeps what a lens is and the boundary rule; the full description, moved from the
router unchanged, is below. Import and management procedure: `references/agent-import.md`.

## Off by default, and the active set

Lenses are **off by default**. A repo turns them on with `<home>/lenses.json`, committed with the repo
(`{"enabled": true, "global": ["name", ...], "repo_off": ["name", ...]}`; a missing file means off, only a
literal `true` enables it, a malformed file is off and reported). `python <skill>/scripts/lenses.py status`
shows the **active lenses** (`enable`, `disable`, `select`, `deselect`, `repo-off`, `repo-on` change them).
A role reads **only the active set**; the rest of this page describes what a lens is once it is active.

## What a lens is

A repo may carry operator-imported **lenses** in `<home>/agents/` (default `.gitos/agents/`) —
domain-tagged specialist context the operator brought in (a math lens, a niche-research lens, …),
catalogued in `<home>/agents/index.md`. A lens is **injected context, not a dispatched role**:
whatever role you are in, when your current work matches an active lens's `domain` / `when-to-apply`, read that
lens and fold its guidance into your work — **within your role's boundary**. A lens changes how you
*think* about a domain; it never changes what your role is *allowed to do* (a read-only role stays
read-only; a scoped implementer stays scoped). Lenses are operator-authored *approach* — distinct from
the brain, which holds the project's *facts*.

## Two layers

Lenses resolve from **two layers**: the repo's own `<home>/agents/` and the operator's **global lens
library** at `<skill>/agents/` — the installed skill's own `agents/` directory (registry
`<skill>/agents/index.md`). A repo **selects global lenses by name** (`global` in `lenses.json`, no
wildcard); they are not copied, so an edit to a global lens reaches every repo that selected it. A repo
copy is only for a deliberate local variant. On a name collision the repo's lens wins (more specific).
The same boundary rules govern both layers. The global library is **operator content**: engine updates
never ship, overwrite, or delete it. `agent import` writes the lens to the global library and selects it
in the current repo (repo-only on request), and `upgrade` offers the selection and refreshes any repo copy
from the global library — report-and-ask, so a deliberate local variant survives by declining.

## Managing lenses

Manage them via `references/agent-import.md`:
- `/gitos agent import <path>` — import a prompt as a lens. The **orchestrator normalizes** it into the
  gitos idiom before storing (forward-positive framing, role-boundary-aware phrasing, standard
  vocabulary), preserving the operator's domain substance; the operator confirms the reframe. Raw
  prompts are never stored as-is.
- `/gitos agent list` — print the active and inactive lenses with their layer.

## Matching lenses to the work

You match lenses to the work yourself; no model does. `python scripts/system_one.py lenses <home> --wo NNN`
(or `--text FILE`) only lists the active set with each lens's domain and when-to-apply (no model call, writes
nothing) and reports a lens whose frontmatter cannot be read; the role reads each matching lens itself.
