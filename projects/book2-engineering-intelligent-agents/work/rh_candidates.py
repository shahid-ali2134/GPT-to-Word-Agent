"""Paragraphs StealthWriter humanized but whose formula placeholders were mangled.

  python rh_candidates.py dump <NN> <out.json>     candidates of all chunk files of chapter NN
  python rh_candidates.py merge <NN> <fixed.json>  [{"id", "text"}] -> chunk files ("finished_text")

The fixer only puts every [[Mk]] back into StealthWriter's candidate wording (no other changes);
`rehumanize_book.py patch` then uses "finished_text" for those paragraphs."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rehumanize_book import OUT, PH, _chunk_files, mechanical, unlock  # noqa: E402

cmd, n = sys.argv[1], sys.argv[2].zfill(2)
ex = {e["id"]: e for e in json.load(open(os.path.join(OUT, f"ch{n}.json"), encoding="utf-8"))}
if cmd == "dump":
    out = []
    for f in _chunk_files(n):
        for b in json.load(open(f, encoding="utf-8")):
            c = b.get("humanized_candidate")
            if not b.get("humanized") and c:
                cand = mechanical(unlock(re.sub(r"\$\$?([^$]+?)\$\$?", r"$\1$", c)))
                out.append({"id": b["id"], "candidate": cand, "before": b["export_text"],
                            "math": ex[b["id"]].get("math"),
                            "missing": sorted(set(PH.findall(b["export_text"])) - set(PH.findall(cand)))})
    json.dump(out, open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(out)} candidates -> {sys.argv[3]}")
elif cmd == "merge":
    fixed = {x["id"]: x["text"] for x in json.load(open(sys.argv[3], encoding="utf-8"))}
    for f in _chunk_files(n):
        blocks = json.load(open(f, encoding="utf-8"))
        hit = 0
        for b in blocks:
            if b["id"] in fixed:
                t = fixed[b["id"]]
                if sorted(PH.findall(t)) != sorted(PH.findall(b["export_text"])):
                    print(f"id {b['id']}: placeholders still wrong; not merged")
                    continue
                b["finished_text"] = t
                hit += 1
        if hit:
            json.dump(blocks, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print(f"{os.path.basename(f)}: {hit} merged")
