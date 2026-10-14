"""Replace the prose of existing Word paragraphs with humanized text while
keeping their inline equations (OMML) untouched.

Input: a JSON list of {"old": <block text as appended>, "new": <humanized text>}.
Both texts must contain the same inline math spans in the same order; the
prose between spans is written into the paragraph's text runs between its
equation objects. Back up the docx first.
Usage: python patch_word_paragraphs.py <docx> <patches.json> [--dry-run]"""
import json
import re
import sys

from docx import Document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
MATH = re.compile(r"\$\$.+?\$\$|(?<!\\)\$[^$\n]+?(?<!\\)\$", re.S)


def split(text):
    return MATH.split(text), MATH.findall(text)


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def para_groups(p):
    """Children of the paragraph split at each oMath: list of lists of w:r."""
    groups, n_math = [[]], 0
    for el in p._p:
        if el.tag in (f"{M}oMath", f"{M}oMathPara"):
            groups.append([])
            n_math += 1
        elif el.tag == f"{W}r":
            groups[-1].append(el)
    return groups, n_math


def group_text(runs):
    return "".join(t.text or "" for r in runs for t in r.iter(f"{W}t"))


def main():
    docx, patches_file = sys.argv[1], sys.argv[2]
    dry = "--dry-run" in sys.argv
    doc = Document(docx)
    patches = json.load(open(patches_file, encoding="utf-8"))
    for k, pt in enumerate(patches):
        old_txt, old_math = split(pt["old"])
        new_txt, new_math = split(pt["new"])
        if old_math != new_math:
            print(f"patch {k}: math spans differ between old and new; skipped")
            continue
        target = None
        for p in doc.paragraphs:
            groups, n_math = para_groups(p)
            if n_math != len(old_math):
                continue
            if all(norm(group_text(g)) == norm(o.replace("**", "").replace("*", ""))
                   for g, o in zip(groups, old_txt)):
                target = (p, groups)
                break
        if not target:
            print(f"patch {k}: paragraph not found in Word: {pt['old'][:80]!r}")
            continue
        p, groups = target
        for g, new in zip(groups, new_txt):
            if not g:
                if new.strip():
                    print(f"patch {k}: no text run to hold {new[:40]!r}; skipped segment")
                continue
            ts = [t for r in g for t in r.iter(f"{W}t")]
            ts[0].text = new
            ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            for t in ts[1:]:
                t.text = ""
        print(f"patch {k}: replaced ({'dry run' if dry else 'written'}): {pt['new'][:70]!r}")
    if not dry:
        doc.save(docx)


if __name__ == "__main__":
    main()
