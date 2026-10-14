"""Exact page numbers per chapter from Word itself (COM, read-only copy).
Usage: python page_count.py <docx>"""
import os
import shutil
import sys
import tempfile

import win32com.client

src = os.path.abspath(sys.argv[1])
tmp = os.path.join(tempfile.gettempdir(), "page_count_copy.docx")
shutil.copy2(src, tmp)
word = win32com.client.DispatchEx("Word.Application")
word.Visible = False
word.DisplayAlerts = 0
try:
    doc = word.Documents.Open(tmp, ReadOnly=True, AddToRecentFiles=False)
    doc.Repaginate()
    total = doc.ComputeStatistics(2)  # wdStatisticPages
    starts = []
    for p in doc.Paragraphs:
        try:
            style = p.Style.NameLocal
        except Exception:
            continue
        if style in ("Heading 1", "Überschrift 1") and p.Range.Text.strip():
            starts.append((p.Range.Text.strip()[:45], p.Range.Information(3)))  # wdActiveEndPageNumber
    print(f"total pages: {total}")
    for k, (title, page) in enumerate(starts):
        end = starts[k + 1][1] - 1 if k + 1 < len(starts) else total
        print(f"{end - page + 1:4d} pages  (p.{page}-{end})  {title}")
    doc.Close(False)
finally:
    word.Quit()
    os.remove(tmp)
