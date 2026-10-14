"""Find Word paragraphs that still carry ChatGPT's wording (not humanized).

Compares every Normal paragraph in the Word file with all saved ChatGPT replies
(work/chNN/*.md, figure/rule chatter excluded by length) sentence by sentence,
ignoring math. A paragraph is flagged when at least half of its sentences
appear word for word in a ChatGPT reply.
Usage: python gpt_text_check.py <docx> [threshold=0.5]"""
import glob
import os
import re
import sys

from docx import Document

HERE = os.path.dirname(os.path.abspath(__file__))
MATH = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.S)
SPLIT = re.compile(r"(?<=[.!?:])\s+")


def norm(s: str) -> str:
    s = s.replace("**", "").replace("*", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def sentences(text: str) -> list[str]:
    out = []
    for s in SPLIT.split(text):
        n = norm(s)
        if len(n.split()) >= 8:
            out.append(n)
    return out


gpt = set()
for f in glob.glob(os.path.join(HERE, "ch*", "*.md")):
    md = open(f, encoding="utf-8").read()
    for line in md.split("\n"):
        line = MATH.sub(" ", line)
        gpt.update(sentences(line))

doc = Document(sys.argv[1])
thr = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
chapter, heading = "", ""
flagged, total_sent, total_hit = [], 0, 0
for p in doc.paragraphs:
    style = p.style.name if p.style is not None else ""
    if style.startswith("Heading 1"):
        chapter = p.text.strip()
    if style.startswith("Heading"):
        heading = p.text.strip()
        continue
    if style == "Caption" or not p.text.strip():
        continue
    sents = sentences(p.text)
    if not sents:
        continue
    hits = [s for s in sents if s in gpt]
    total_sent += len(sents)
    total_hit += len(hits)
    if len(hits) / len(sents) >= thr:
        flagged.append((chapter, heading, len(hits), len(sents), p.text[:110]))

print(f"Word sentences checked: {total_sent}; identical to ChatGPT: {total_hit} "
      f"({100 * total_hit / max(total_sent, 1):.1f}%)")
print(f"paragraphs with >= {int(thr * 100)}% ChatGPT sentences: {len(flagged)}")
for ch, h, a, b, t in flagged:
    print(f"- [{ch[:30]} | {h[:45]}] {a}/{b}: {t}")
