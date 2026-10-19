"""Pre-append safety scan: control characters from broken JSON escapes
(e.g. "\rho" read as CR + "ho", "\theta" as TAB + "heta").
Usage: python scan_blocks.py <blocks.json> [...]; exit 1 if anything found."""
import json
import re
import sys

BAD = re.compile(r"[\x00-\x08\x09\x0b\x0c\x0d\x0e-\x1f]")
found = 0
for f in sys.argv[1:]:
    d = json.load(open(f, encoding="utf-8"))
    blocks = d["blocks"] if isinstance(d, dict) else d
    for i, b in enumerate(blocks):
        vals = [(k, b.get(k)) for k in ("text", "latex", "caption")]
        vals += [("cell", c) for row in b.get("rows") or [] for c in row]
        for k, v in vals:
            if isinstance(v, str) and BAD.search(v):
                m = BAD.search(v)
                print(f"{f} block {i} {k}: {v[max(0, m.start() - 15):m.start() + 15]!r}")
                found += 1
print(f"control characters: {found}")
sys.exit(1 if found else 0)
