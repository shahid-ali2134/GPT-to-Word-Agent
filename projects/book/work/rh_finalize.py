"""Build chapter NN's Word patches: humanized chunks + mechanical fixes + reviewer fixes.

  python rh_finalize.py <NN> [extra.json]

Runs `rehumanize_book.py patch NN`, then applies every rh_review/chNNc*_fixes.json (and the
optional extra [{"id","old","new"}] file, e.g. first-person fixes) to rehumanize_apply/chNN.patches.json.
Prints each first-person sentence still left. Then: backup + style_cleanup.py apply."""
import glob
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rehumanize_book import APPLY, FIRST_PERSON, PH  # noqa: E402

n = sys.argv[1].zfill(2)
subprocess.run([sys.executable, os.path.join(HERE, "rehumanize_book.py"), "patch", n], check=True)
pf = os.path.join(APPLY, f"ch{n}.patches.json")
P = {p["id"]: p["new"] for p in json.load(open(pf, encoding="utf-8"))}
files = sorted(glob.glob(os.path.join(HERE, "rh_review", f"ch{n}c*_fixes.json")))
files += sys.argv[2:]
done = miss = 0
for f in files:
    for fx in json.load(open(f, encoding="utf-8")):
        t = P.get(fx["id"])
        if t is None or t.count(fx["old"]) != 1:
            print(f"MISS {os.path.basename(f)} id {fx['id']}: {fx['old'][:70]}")
            miss += 1
            continue
        P[fx["id"]] = t.replace(fx["old"], fx["new"])
        done += 1
json.dump([{"id": k, "new": v} for k, v in P.items()], open(pf, "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"fixes applied {done}, missed {miss}, from {len(files)} file(s)")
for i, t in P.items():
    for s in re.split(r"(?<=[.!?])\s+", t):
        if FIRST_PERSON.search(PH.sub(" ", s)):
            print(f"FIRST PERSON {i} | {s}")
