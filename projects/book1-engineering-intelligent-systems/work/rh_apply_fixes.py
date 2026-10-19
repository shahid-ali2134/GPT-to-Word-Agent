"""Apply a fewest-word fixes file to chapter NN as it is in Word now, then make scan parts.

  python rh_apply_fixes.py <NN> <fixes.json> <docx>

fixes: [{"id", "old", "new"}] on the current Word text ([[Mk]] = inline equations). Backs up
Word, writes only the changed paragraphs (style_cleanup apply keeps the equation objects), then
writes rehumanize/chNN.scan.txt and chNN.scan1..3.txt (~4,000 words each) for stealthwriter_check_ai."""
import datetime
import json
import math
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rehumanize_book import APPLY, OUT, PH  # noqa: E402

n, fixes, docx = sys.argv[1].zfill(2), sys.argv[2], sys.argv[3]
py = sys.executable
shutil.rmtree(APPLY, ignore_errors=True)
subprocess.run([py, os.path.join(HERE, "style_cleanup.py"), "export", docx, APPLY], check=True,
               capture_output=True)
for f in os.listdir(APPLY):
    if f != f"ch{n}.json":
        os.remove(os.path.join(APPLY, f))
cur = {e["id"]: e["text"] for e in json.load(open(os.path.join(APPLY, f"ch{n}.json"), encoding="utf-8"))}
P, miss = {}, 0
for fx in json.load(open(fixes, encoding="utf-8")):
    t = P.get(fx["id"], cur.get(fx["id"]))
    if t is None or t.count(fx["old"]) != 1:
        print(f"MISS id {fx['id']}: {fx['old'][:70]}")
        miss += 1
        continue
    P[fx["id"]] = t.replace(fx["old"], fx["new"])
for i, t in P.items():
    assert sorted(PH.findall(t)) == sorted(PH.findall(cur[i])), f"placeholders changed in {i}"
json.dump([{"id": k, "new": v} for k, v in P.items()],
          open(os.path.join(APPLY, f"ch{n}.patches.json"), "w", encoding="utf-8"), ensure_ascii=False)
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy(docx, os.path.join(HERE, "..", "backups", f"{stamp}_before_ch{n}_fixes.docx"))
r = subprocess.run([py, os.path.join(HERE, "style_cleanup.py"), "apply", docx, APPLY],
                   capture_output=True, text=True)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:], f"| missed {miss}")
subprocess.run([py, os.path.join(HERE, "rehumanize_book.py"), "scantext", str(int(n)), docx],
               check=True, capture_output=True)
t = open(os.path.join(OUT, f"ch{n}.scan.txt"), encoding="utf-8").read().split("\n\n")
W = sum(len(p.split()) for p in t)
k = math.ceil(W / 4000)
tgt, parts, w = W / k, [[]], 0
for p in t:
    if w >= tgt * len(parts) and len(parts) < k:
        parts.append([])
    parts[-1].append(p)
    w += len(p.split())
for i, pp in enumerate(parts, 1):
    open(os.path.join(OUT, f"ch{n}.scan{i}.txt"), "w", encoding="utf-8").write("\n\n".join(pp))
print("scan parts:", [sum(len(p.split()) for p in pp) for pp in parts])
