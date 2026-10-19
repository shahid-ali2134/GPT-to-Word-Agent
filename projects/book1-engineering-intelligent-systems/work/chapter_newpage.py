"""Make every chapter heading (Heading 1 with text) after the first start on a
new page. Idempotent. Usage: python chapter_newpage.py <docx>
Needed until the book-agent server is restarted with the docx_writer change."""
import sys

from docx import Document

doc = Document(sys.argv[1])
headings = [p for p in doc.paragraphs
            if p.style is not None and p.style.name == "Heading 1" and p.text.strip()]
changed = 0
for p in headings[1:]:
    if not p.paragraph_format.page_break_before:
        p.paragraph_format.page_break_before = True
        changed += 1
if changed:
    doc.save(sys.argv[1])
print(f"chapter headings: {len(headings)}; set new page on {changed}")
