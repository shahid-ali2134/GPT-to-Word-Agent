"""End-of-chapter check on the Word document: numbered equation references,
Figure/Table references pointing past the last caption, leftover LaTeX/markdown,
and duplicate headings. Usage: python chapter_check.py <docx>"""
import re
import sys
from collections import Counter

from docx import Document

doc = Document(sys.argv[1])
paras = [p for p in doc.paragraphs]
text = "\n".join(p.text for p in paras)

fig_caps = [p for p in paras if p.style is not None and p.style.name == "Caption" and p.text.startswith("Figure")]
tab_caps = [p for p in paras if p.style is not None and p.style.name == "Caption" and p.text.startswith("Table")]
nfig, ntab = len(fig_caps), len(tab_caps)

body = "\n".join(p.text for p in paras if p.style is None or p.style.name != "Caption")
problems = []
for m in re.finditer(r"\b(?:Equation|Eq\.)\s*\(?\d+", body):
    problems.append(f"numbered equation reference: {body[max(0, m.start() - 40):m.end() + 10]!r}")
for m in re.finditer(r"\bFigures?\s+(\d+)", body):
    if int(m.group(1)) > nfig:
        problems.append(f"Figure {m.group(1)} referenced but only {nfig} captions")
for m in re.finditer(r"\bTables?\s+(\d+)", body):
    if int(m.group(1)) > ntab:
        problems.append(f"Table {m.group(1)} referenced but only {ntab} captions")
for pat in (r"\$", r"\\[a-zA-Z]{2,}", r"\*\*", r"^#+\s", r"<text", r"Placement:", r"�"):
    for m in re.finditer(pat, body, re.M):
        problems.append(f"leftover {pat!r}: {body[max(0, m.start() - 30):m.end() + 30]!r}")
heads = Counter((p.style.name, p.text.strip()) for p in paras
                if p.style is not None and p.style.name.startswith("Heading") and p.text.strip())
for (s, t), c in heads.items():
    if c > 1 and t != "Chapter Summary":
        problems.append(f"duplicate heading {s}: {t}")

print(f"figure captions: {nfig}, table captions: {ntab}")
print("\n".join(problems) if problems else "no problems")
