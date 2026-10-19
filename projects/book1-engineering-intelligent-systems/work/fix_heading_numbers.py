"""Strip hand-typed section numbers ("12.5 ", "12.5.1 ") from Heading 2/3
paragraphs: Word's heading styles number them automatically, so a typed
number shows twice. Usage: python fix_heading_numbers.py <docx> [--dry-run]"""
import re
import sys

from docx import Document

NUM = re.compile(r"^\s*\d+(\.\d+)+\s+")


def main():
    path, dry = sys.argv[1], "--dry-run" in sys.argv
    doc = Document(path)
    n = 0
    for p in doc.paragraphs:
        if p.style is None or p.style.name not in ("Heading 2", "Heading 3"):
            continue
        if not NUM.match(p.text):
            continue
        for r in p.runs:
            if r.text.strip():
                r.text = NUM.sub("", r.text, count=1)
                break
        n += 1
        print("fixed:", p.text[:70])
    print(f"{n} heading(s) fixed")
    if n and not dry:
        doc.save(path)


if __name__ == "__main__":
    main()
