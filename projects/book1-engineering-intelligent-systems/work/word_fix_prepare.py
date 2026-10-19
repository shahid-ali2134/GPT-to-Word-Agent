"""Build work/fix/word_fix.blocks.json (the 6 Word paragraphs left in ChatGPT's
wording after failed StealthWriter runs) for humanize_blocks, and, with
--patches, turn the humanized result into patches for patch_word_paragraphs.py."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGETS = [("ch01/r02", 30), ("ch03/r05", 7), ("ch03/r05", 56),
           ("ch03/r06", 7), ("ch03/r06", 55), ("ch06/r03", 27)]
FIX = os.path.join(HERE, "fix", "word_fix.blocks.json")

if "--patches" not in sys.argv:
    os.makedirs(os.path.dirname(FIX), exist_ok=True)
    out = []
    for f, i in TARGETS:
        b = json.load(open(os.path.join(HERE, f + ".blocks.json"), encoding="utf-8"))[i]
        out.append({"type": "body", "text": b["text"], "source": f"{f}#{i}"})
    json.dump(out, open(FIX, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {FIX} ({len(out)} paragraphs)")
else:
    fixed = json.load(open(FIX, encoding="utf-8"))
    patches = [{"old": b["original"], "new": b["text"], "source": b["source"]}
               for b in fixed if b.get("humanized")]
    json.dump(patches, open(os.path.join(HERE, "fix", "patches.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"{len(patches)} patch(es); not humanized: "
          f"{[b['source'] for b in fixed if not b.get('humanized')]}")
