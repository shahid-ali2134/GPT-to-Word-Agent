"""AI-gate diagnosis: build chapter NN's scan text as pure StealthWriter output (no reviewer
fixes), cut at the same paragraph boundaries as rehumanize/chNN.scan<k>.txt.

  python rh_variant.py <NN> <part k>   -> rehumanize/chNN.raw<k>.txt
Compare its "Check for AI" score with chNN.scan<k>.txt: if raw is green and the final text is
red, the fixes in that part pulled it down (replace them with StealthWriter alternatives)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rehumanize_book import OUT, PH, _chunk_files, mechanical, unlock  # noqa: E402

n, k = sys.argv[1].zfill(2), int(sys.argv[2])
ex = [e for e in json.load(open(os.path.join(OUT, f"ch{n}.json"), encoding="utf-8")) if e["kind"] == "body"]
raw = {}
for f in _chunk_files(n):
    for b in json.load(open(f, encoding="utf-8")):
        if b.get("humanized"):
            raw[b["id"]] = mechanical(unlock(b["text"]))
        elif b.get("humanized_candidate"):
            raw[b["id"]] = b.get("finished_text") or b["export_text"]
sym = lambda e, t: PH.sub(lambda m: (e.get("math") or {}).get(m.group(0)[2:-2], ""), t)  # noqa: E731
paras = [sym(e, raw.get(e["id"], e["text"])) for e in ex]
start = sum(len(open(os.path.join(OUT, f"ch{n}.scan{i}.txt"), encoding="utf-8").read().split("\n\n"))
            for i in range(1, k))
cnt = len(open(os.path.join(OUT, f"ch{n}.scan{k}.txt"), encoding="utf-8").read().split("\n\n"))
path = os.path.join(OUT, f"ch{n}.raw{k}.txt")
open(path, "w", encoding="utf-8").write("\n\n".join(paras[start:start + cnt]))
print(path, sum(len(p.split()) for p in paras[start:start + cnt]), "words")
