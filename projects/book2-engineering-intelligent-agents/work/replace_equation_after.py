"""Replace the display equation that follows a given body paragraph with new
LaTeX (converted to Word math with the pipeline's own converter).
Back up the docx first.
Usage: python replace_equation_after.py <docx> "<start of anchor paragraph>" "<new latex>" [--dry-run]"""
import os
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from docx import Document  # noqa: E402

from tools.blocks import latex_to_omml  # noqa: E402

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def main():
    docx, start, latex = sys.argv[1], norm(sys.argv[2]), sys.argv[3]
    dry = "--dry-run" in sys.argv
    doc = Document(docx)
    paras = doc.paragraphs
    idx = [i for i, p in enumerate(paras) if norm(p.text).startswith(start)]
    if len(idx) != 1:
        sys.exit(f"expected exactly 1 anchor paragraph, found {len(idx)}")
    i = idx[0] + 1
    while i < len(paras) and not norm(paras[i].text) and not any(True for _ in paras[i]._p.iter(f"{M}oMath")):
        i += 1
    target = paras[i]
    olds = list(target._p.iter(f"{M}oMath"))
    if len(olds) != 1 or norm(target.text):
        sys.exit("no single standalone display equation after the anchor")
    new = latex_to_omml(latex)
    if new is None:
        sys.exit("LaTeX did not convert")
    if new.tag != f"{M}oMath":
        inner = list(new.iter(f"{M}oMath"))
        if not inner:
            sys.exit(f"converter returned {new.tag}")
        new = inner[0]
    print(f"anchor #{idx[0]}; replacing equation in #{i}")
    if not dry:
        old = olds[0]
        old.getparent().replace(old, new)
        doc.save(docx)
        print("saved")


if __name__ == "__main__":
    main()
