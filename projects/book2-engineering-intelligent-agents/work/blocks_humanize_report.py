"""Report, per blocks file, text blocks whose wording is still ChatGPT's:
body/list_item blocks never humanized, and humanized blocks whose text came
back unchanged. Usage: python blocks_humanize_report.py"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)


def plain(s):
    return re.sub(r"\s+", " ", MATH.sub(" ", s)).strip()


tot = {"body": 0, "not_humanized": 0, "math_only": 0, "unchanged": 0, "list_item": 0}
for f in sorted(glob.glob(os.path.join(HERE, "ch*", "r*.blocks.json"))):
    blocks = json.load(open(f, encoding="utf-8"))
    rel = os.path.relpath(f, HERE)
    for i, b in enumerate(blocks):
        t = b.get("type")
        if t == "list_item":
            tot["list_item"] += 1
            if not b.get("humanized"):
                print(f"{rel} #{i} list_item NOT humanized: {b['text'][:90]}")
        if t != "body":
            continue
        tot["body"] += 1
        if b.get("humanize") is False:
            tot["math_only"] += 1
            print(f"{rel} #{i} humanize=false ({b.get('humanize_note', 'no note')}): {b['text'][:90]}")
        elif not b.get("humanized"):
            tot["not_humanized"] += 1
            print(f"{rel} #{i} NOT humanized: {b['text'][:90]}")
        elif b.get("original") and plain(b["original"]) == plain(b["text"]):
            tot["unchanged"] += 1
            print(f"{rel} #{i} humanized but UNCHANGED: {b['text'][:90]}")
print(tot)
