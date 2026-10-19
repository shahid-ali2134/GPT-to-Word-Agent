"""Tools for compressing the book to 25-26 pages per chapter.

  python compress_tools.py base <src.docx> <out.docx>
      copy of the book with everything from the first chapter heading on removed
      (front matter and table of contents kept)
  python compress_tools.py render <base.docx> <chapter_dir> <prefix>
      append <chapter_dir>/<prefix>r*.blocks.json in order to a temp copy of the
      base and print the chapter's page count from Word, plus word counts
  python compress_tools.py words <chapter_dir> <prefix>
      prose word count per unit file
"""
import glob
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def make_base(src, out):
    from docx import Document
    doc = Document(src)
    body = doc.element.body
    cut = None
    for p in doc.paragraphs:
        if p.style is not None and p.style.name == "Heading 1" and p.text.strip():
            cut = p._p
            break
    if cut is None:
        raise SystemExit("no chapter heading found")
    remove, on = [], False
    for el in list(body):
        if el is cut:
            on = True
        if on and el.tag != f"{W}sectPr":
            remove.append(el)
    for el in remove:
        body.remove(el)
    doc.save(out)
    print(f"base saved: {out} ({len(remove)} elements removed)")


def unit_files(chapter_dir, prefix):
    return sorted(glob.glob(os.path.join(chapter_dir, f"{prefix}r*.blocks.json")))


def words(chapter_dir, prefix):
    total = 0
    for f in unit_files(chapter_dir, prefix):
        b = json.load(open(f, encoding="utf-8"))
        n = sum(len(x["text"].split()) for x in b if x.get("type") in ("body", "list_item"))
        eq = sum(1 for x in b if x.get("type") == "equation")
        total += n
        print(f"{os.path.basename(f)}: {n} prose words, {eq} equations")
    print(f"total prose words: {total}")
    return total


def pages(path):
    import win32com.client
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True, AddToRecentFiles=False)
        doc.Repaginate()
        n = doc.ComputeStatistics(2)
        doc.Close(False)
        return n
    finally:
        word.Quit()


def render(base, chapter_dir, prefix):
    from tools import docx_writer
    tmp = os.path.join(tempfile.gettempdir(), "compress_render.docx")
    shutil.copy2(base, tmp)
    base_pages = pages(tmp)
    for f in unit_files(chapter_dir, prefix):
        docx_writer.append_blocks(json.load(open(f, encoding="utf-8")), tmp)
    total = pages(tmp)
    words(chapter_dir, prefix)
    print(f"CHAPTER PAGES: {total - base_pages} (base {base_pages}, total {total})")
    os.remove(tmp)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "base":
        make_base(sys.argv[2], sys.argv[3])
    elif cmd == "render":
        render(sys.argv[2], sys.argv[3], sys.argv[4])
    elif cmd == "words":
        words(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
