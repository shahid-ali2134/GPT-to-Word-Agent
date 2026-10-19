"""Put StealthWriter alternatives into a chunk's fixes file (they replace the hand fixes for
the same sentence). python rh_alts.py <pairs.json> <fixes.json> <alts.json>
alts: [[id, "current sentence (as on the StealthWriter page)", "chosen option"]]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rehumanize_book import mechanical
pairs = {p["id"]: p["now"] for p in json.load(open(sys.argv[1], encoding="utf-8"))}
out = []
for i, old, new in json.load(open(sys.argv[3], encoding="utf-8")):
    o = mechanical(old)
    if pairs[i].count(o) != 1:
        print("NOT FOUND", i, o[:60]); continue
    out.append({"id": i, "cat": "ALT", "old": o, "new": mechanical(new)})
fx = json.load(open(sys.argv[2], encoding="utf-8"))
keep = [f for f in fx if f.get("cat") == "ALT" or not any(f["id"] == a["id"] and f["old"] in a["old"] for a in out)]
json.dump(out + [f for f in keep if f.get("cat") != "ALT" or f not in out], open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"alternatives {len(out)}, hand fixes kept {sum(1 for f in keep if f.get('cat') != 'ALT')} of {sum(1 for f in fx if f.get('cat') != 'ALT')}")
