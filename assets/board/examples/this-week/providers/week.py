"""Provider `week`: the open orders the ledger touched in the last 7 days. The board runs this file in its own `python -I`
process (argument 1 is the home, the working directory too) whenever the home changes, and shows the one JSON value it prints as
`state.ext.week` to every view. It reads files only; a crash, a hang or output that is not one JSON value is an `errors` entry
on the board and the page keeps working."""
import json
import re
import sys
import time
from pathlib import Path

DAYS = 7
cutoff = time.time() - DAYS * 86400
touched = []
for p in sorted((Path(sys.argv[1]) / "work-orders").glob("WO-*")):        # open and parked orders; resolved/ does not match
    m = re.match(r"WO-(\d{3})", p.name)
    files = [p] if p.is_file() else list(p.rglob("*.md"))                   # a folder order: the order and its slices
    stamp = max((f.stat().st_mtime for f in files), default=0)
    if m and stamp >= cutoff:
        touched.append({"id": m.group(1), "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stamp))})
touched.sort(key=lambda t: t["at"], reverse=True)
print(json.dumps({"days": DAYS, "touched": touched}))
