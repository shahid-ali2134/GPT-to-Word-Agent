"""Remove the display equation that directly follows a given body paragraph
(plus one adjacent blank spacer paragraph), e.g. to drop an equation that
repeats one defined earlier in the book. Back up the docx first.
Usage: python remove_equation_after.py <docx> "<start of the body paragraph text>" [--dry-run]"""
import re
import sys

from docx import Document

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def has_math(p):
    return any(el.tag in (f"{M}oMath", f"{M}oMathPara") for el in p._p.iter())


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def main():
    docx, start = sys.argv[1], norm(sys.argv[2])
    dry = "--dry-run" in sys.argv
    doc = Document(docx)
    paras = doc.paragraphs
    idx = [i for i, p in enumerate(paras) if norm(p.text).startswith(start)]
    if len(idx) != 1:
        sys.exit(f"expected exactly 1 anchor paragraph, found {len(idx)}")
    i = idx[0] + 1
    remove = []
    while i < len(paras) and not norm(paras[i].text) and not has_math(paras[i]):
        remove.append(paras[i])  # blank spacer(s) before the equation
        i += 1
    if i >= len(paras) or not has_math(paras[i]) or norm(paras[i].text):
        sys.exit("no standalone display equation right after the anchor paragraph")
    remove.append(paras[i])
    j = i + 1
    if j < len(paras) and not norm(paras[j].text) and not has_math(paras[j]):
        remove.append(paras[j])  # blank spacer after the equation
    print(f"anchor #{idx[0]}; removing {len(remove)} paragraph(s) starting at #{i}")
    if not dry:
        for p in remove:
            p._p.getparent().remove(p._p)
        doc.save(docx)
        print("saved")


if __name__ == "__main__":
    main()
