"""Book-wide repetition check over every blocks file the ledger says is in Word.

Finds: identical display equations (normalized LaTeX), near-duplicate body
sentences (same 12-word shingle), duplicate figure images (sha1) or captions,
and duplicate table titles. Optional extra blocks files (not yet in Word) are
checked against the book too.

Usage: python dup_check.py [extra.blocks.json ...]
"""
import hashlib
import json
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.dirname(HERE)
SHINGLE = 12


def written_units():
    led = json.load(open(os.path.join(BOOK, "ledger.json"), encoding="utf-8"))
    chapters = led.get("chapters", led)
    out = []
    for ch, entry in chapters.items():
        if not isinstance(entry, dict):
            continue
        sections = entry.get("sections") or {}
        # compressed units cNN replaced the original rNN units (same index) in Word
        n_comp = sum(1 for u in sections if re.fullmatch(r"c\d+", u))
        for unit, s in sections.items():
            m = re.fullmatch(r"r(\d+)", unit)
            if m and int(m.group(1)) <= n_comp:
                continue
            if isinstance(s, dict) and s.get("status") == "written" and s.get("blocks_file"):
                path = os.path.normpath(s["blocks_file"].replace("/", os.sep))
                if os.path.exists(path):
                    out.append((f"ch{ch}/{unit}", path))
    return out


def norm_eq(tex):
    t = re.sub(r"\s+", "", tex)
    t = re.sub(r"\\(left|right|,|;|!|quad|qquad)", "", t)
    return t


def words(text):
    text = re.sub(r"\$[^$]*\$", " MATH ", text)
    return re.findall(r"[a-z0-9]+", text.lower())


def main():
    units = written_units()
    for extra in sys.argv[1:]:
        units.append(("NEW:" + os.path.basename(extra), os.path.abspath(extra)))

    eqs = defaultdict(list)
    shingles = defaultdict(set)
    imgs = defaultdict(list)
    caps = defaultdict(list)
    tables = defaultdict(list)

    for label, path in units:
        blocks = json.load(open(path, encoding="utf-8"))
        for i, b in enumerate(blocks):
            t = b.get("type")
            where = f"{label}#{i}"
            if t == "equation":
                key = norm_eq(b.get("latex") or b.get("text") or "")
                if len(key) > 12:
                    eqs[key].append(where)
            elif t in ("body", "list_item"):
                w = words(b.get("text", ""))
                for k in range(0, max(0, len(w) - SHINGLE + 1)):
                    sh = " ".join(w[k:k + SHINGLE])
                    if sh.count("math") < 3:
                        shingles[sh].add(where)
            elif t == "figure":
                img = b.get("image") or b.get("path") or ""
                if img and os.path.exists(img):
                    imgs[hashlib.sha1(open(img, "rb").read()).hexdigest()].append(where)
                cap = re.sub(r"^figure\s*\d+\s*", "", (b.get("caption") or "").lower()).strip()
                if cap:
                    caps[cap].append(where)
            elif t == "table":
                title = re.sub(r"^table\s*\d+\s*", "", (b.get("caption") or b.get("title") or "").lower()).strip()
                if title:
                    tables[title].append(where)

    def report(name, groups, min_units=2):
        hits = []
        for key, locs in groups.items():
            units_hit = {l.split("#")[0] for l in locs}
            if len(units_hit) >= min_units:
                hits.append((key, sorted(locs)))
        print(f"== {name}: {len(hits)}")
        for key, locs in hits[:60]:
            print(f"  {key[:110]}\n     -> {', '.join(locs)}")
        return len(hits)

    print(f"units checked: {len(units)}")
    n = report("duplicate display equations", eqs)
    # sentence overlap: merge shingles into unit pairs
    pairs = defaultdict(set)
    for sh, locs in shingles.items():
        locs = sorted(locs)
        if len({l.split('#')[0] for l in locs}) >= 2:
            for a in locs:
                for b in locs:
                    if a < b and a.split('#')[0] != b.split('#')[0]:
                        pairs[(a, b)].add(sh)
    print(f"== repeated passages (shared {SHINGLE}-word runs across units): {len(pairs)}")
    for (a, b), shs in sorted(pairs.items(), key=lambda x: -len(x[1]))[:60]:
        print(f"  {a} <> {b}: {len(shs)} runs, e.g. '{sorted(shs)[0]}'")
    n += len(pairs)
    n += report("duplicate figure images", imgs)
    n += report("duplicate figure captions", caps)
    n += report("duplicate table titles", tables)
    print("TOTAL", n)


if __name__ == "__main__":
    main()
