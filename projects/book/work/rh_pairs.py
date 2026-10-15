"""Review pairs for a humanized chunk: python rh_pairs.py <NN> <chunk-blocks-file> <out.json>
Each pair: id, now (humanized + mechanical fixes, math as [[Mk]]), before, math (symbols)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rehumanize_book import OUT, mechanical, unlock  # noqa: E402

n, chunk, out = sys.argv[1].zfill(2), sys.argv[2], sys.argv[3]
ex = {e["id"]: e for e in json.load(open(os.path.join(OUT, f"ch{n}.json"), encoding="utf-8"))}
pairs = [{"id": b["id"], "now": mechanical(unlock(b["text"])), "before": b["export_text"],
          "math": ex[b["id"]].get("math")}
         for b in json.load(open(chunk, encoding="utf-8")) if b.get("humanized")]
json.dump(pairs, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{len(pairs)} pairs, {sum(1 for p in pairs if p['math'])} with math -> {out}")
