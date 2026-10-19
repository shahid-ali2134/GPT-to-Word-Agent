"""Replace exact text inside body runs of the Word file (each match must sit
within one run; equations are never touched).
Usage: python replace_text.py <docx> "<old>" "<new>" [--dry-run]"""
import sys

from docx import Document


def main():
    path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
    dry = "--dry-run" in sys.argv
    doc = Document(path)
    n = 0
    for p in doc.paragraphs:
        if old not in p.text:
            continue
        hit = False
        for r in p.runs:
            if old in r.text:
                r.text = r.text.replace(old, new)
                hit = True
                n += 1
        print(("replaced: " if hit else "SPLIT ACROSS RUNS, not replaced: ") + p.text[:110])
    print(f"{n} replacement(s)")
    if n and not dry:
        doc.save(path)


if __name__ == "__main__":
    main()
