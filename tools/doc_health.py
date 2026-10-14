"""
Whole-document health check for the book's Word file, with automatic repairs.

Checks: numbered equation references, Figure/Table references beyond the last
caption, leftover LaTeX/markdown/ChatGPT text, duplicate headings, figure and
table caption numbering gaps. Repairs: chapter headings after the first start on
a new page.
"""

import re
from collections import Counter

from docx import Document


def check(path: str, fix: bool = True) -> dict:
    doc = Document(path)
    paras = list(doc.paragraphs)
    style = lambda p: p.style.name if p.style is not None else ""
    fixes, problems = [], []

    chapters = [p for p in paras if style(p) == "Heading 1" and p.text.strip()]
    for p in chapters[1:]:
        if not p.paragraph_format.page_break_before:
            if fix:
                p.paragraph_format.page_break_before = True
            fixes.append(f"chapter {p.text[:50]!r} now starts on a new page")

    caps = [p.text for p in paras if style(p) == "Caption"]
    for kind in ("Figure", "Table"):
        nums = [int(m.group(1)) for c in caps for m in [re.match(rf"{kind}\s+(\d+)", c)] if m]
        if nums != list(range(1, len(nums) + 1)):
            problems.append(f"{kind} caption numbers are not 1..{len(nums)} in order")
    nfig = sum(1 for c in caps if c.startswith("Figure"))
    ntab = sum(1 for c in caps if c.startswith("Table"))

    body = "\n".join(p.text for p in paras if style(p) != "Caption")
    for m in re.finditer(r"\b(?:Equation|Eq\.)\s*\(?\d+", body):
        problems.append(f"numbered equation reference: {body[max(0, m.start() - 40):m.end() + 10]!r}")
    for m in re.finditer(r"\bFigures?\s+(\d+)", body):
        if int(m.group(1)) > nfig:
            problems.append(f"Figure {m.group(1)} referenced but only {nfig} figures")
    for m in re.finditer(r"\bTables?\s+(\d+)", body):
        if int(m.group(1)) > ntab:
            problems.append(f"Table {m.group(1)} referenced but only {ntab} tables")
    for pat in (r"\$", r"\\[a-zA-Z]{2,}", r"\*\*", r"^#+\s", r"<text", r"Placement:", r"KEEP\s*TOKEN",
                r"continue to the next section", r"�"):
        for m in re.finditer(pat, body, re.M | re.I):
            problems.append(f"leftover {pat!r}: {body[max(0, m.start() - 30):m.end() + 30]!r}")
    heads = Counter((style(p), p.text.strip()) for p in paras
                    if style(p).startswith("Heading") and p.text.strip())
    for (s, t), c in heads.items():
        if c > 1 and t != "Chapter Summary":
            problems.append(f"duplicate heading {s}: {t}")

    if fix and fixes:
        doc.save(path)
    return {"figures": nfig, "tables": ntab, "chapters": len(chapters),
            "fixes": fixes, "problems": problems}
