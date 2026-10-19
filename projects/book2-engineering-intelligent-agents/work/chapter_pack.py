"""Pack a chapter's crNN units into one file for humanizing (fewer StealthWriter
runs), and split the result back.
  python chapter_pack.py pack  work/chNN   -> work/chNN/c_all.blocks.json
  python chapter_pack.py split work/chNN   -> rewrites work/chNN/crNN.blocks.json
"""
import glob
import json
import os
import sys

d = sys.argv[2]
packed = os.path.join(d, "c_all.blocks.json")
units = sorted(glob.glob(os.path.join(d, "cr*.blocks.json")))

if sys.argv[1] == "pack":
    out = []
    for f in units:
        for b in json.load(open(f, encoding="utf-8")):
            b["_unit"] = os.path.basename(f)
            out.append(b)
    json.dump(out, open(packed, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    words = sum(len(b["text"].split()) for b in out if b["type"] == "body")
    print(f"packed {len(units)} units, {len(out)} blocks, {words} prose words -> {packed}")
else:
    allb = json.load(open(packed, encoding="utf-8"))
    for f in units:
        name = os.path.basename(f)
        mine = [dict(b) for b in allb if b.get("_unit") == name]
        orig = json.load(open(f, encoding="utf-8"))
        if len(mine) != len(orig):
            raise SystemExit(f"{name}: block count changed ({len(orig)} -> {len(mine)})")
        for b in mine:
            b.pop("_unit", None)
        json.dump(mine, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    left = [i for i, b in enumerate(allb) if b["type"] == "body"
            and not b.get("humanized") and b.get("humanize") is not False]
    print(f"split back into {len(units)} units; body blocks not humanized: {left}")
