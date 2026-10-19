"""Loose repetition check: equations with the same STRUCTURE (symbols renamed)
and passages sharing 8-word runs. Prints candidates for human/auditor review.

Usage: python dup_check_loose.py [extra.blocks.json ...]
"""
import json
import re
import sys
from collections import defaultdict

from dup_check import written_units, words

SHINGLE = 8
COMMANDS = {"frac", "sum", "prod", "sqrt", "arg", "max", "min", "exp", "log", "mathbb",
            "cdot", "left", "right", "mid", "in", "le", "leq", "ge", "geq", "lVert", "rVert",
            "begin", "end", "cases", "infty", "partial", "nabla", "top", "operatorname", "approx"}


def eq_shape(tex):
    t = re.sub(r"\\(mathrm|text|operatorname)\{[^}]*\}", "N", tex)
    t = re.sub(r"\\([A-Za-z]+)", lambda m: "\\" + m.group(1) if m.group(1) in COMMANDS else "V", t)
    t = re.sub(r"[A-Za-z]", "V", t)
    t = re.sub(r"\d+", "D", t)
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"V+", "V", t)
    return t


def main():
    units = written_units()
    for extra in sys.argv[1:]:
        units.append(("NEW:" + extra.replace("\\", "/").split("/")[-1], extra))
    shapes = defaultdict(list)
    shing = defaultdict(set)
    for label, path in units:
        for i, b in enumerate(json.load(open(path, encoding="utf-8"))):
            if b.get("type") == "equation":
                tex = b.get("latex") or ""
                s = eq_shape(tex)
                if len(s) >= 25:
                    shapes[s].append((f"{label}#{i}", tex))
            elif b.get("type") in ("body", "list_item"):
                w = words(b.get("text", ""))
                for k in range(len(w) - SHINGLE + 1):
                    sh = " ".join(w[k:k + SHINGLE])
                    if "math" not in sh:
                        shing[sh].add(f"{label}#{i}")
    print("== same-structure equations in different units")
    for s, locs in shapes.items():
        if len({l.split("#")[0] for l, _ in locs}) >= 2:
            for l, tex in locs:
                print(f"  {l}: {tex[:120]}")
            print()
    pairs = defaultdict(set)
    for sh, locs in shing.items():
        locs = sorted(locs)
        if 2 <= len(locs) <= 4:
            for a in locs:
                for b in locs:
                    if a < b and a.split("#")[0] != b.split("#")[0]:
                        pairs[(a, b)].add(sh)
    print("== passages sharing 8-word runs (>=2 runs)")
    for (a, b), shs in sorted(pairs.items(), key=lambda x: -len(x[1])):
        if len(shs) >= 2:
            print(f"  {a} <> {b}: {len(shs)}: {' | '.join(sorted(shs)[:3])}")


if __name__ == "__main__":
    main()
