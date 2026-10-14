"""
Structured content blocks for the Claude-orchestrated workflow.

A section is stored as a JSON list of blocks that Claude can read, review and
edit before anything touches the Word document:

  {"type": "chapter",   "text": "Title"}
  {"type": "heading2",  "num": "7.2",   "text": "Title"}
  {"type": "heading3",  "num": "7.2.1", "text": "Title"}
  {"type": "body",      "text": "Prose with **bold**, *italic* and $x^2$ inline math."}
  {"type": "list_item", "text": "..."}
  {"type": "equation",  "latex": "E = mc^2", "label": "7.3"}      # label optional
  {"type": "table",     "caption": "Title", "rows": [["H1","H2"],["a","b"]]}
  {"type": "figure",    "number": 12, "caption": "Sentence.", "image": "path.png"}

This module converts ChatGPT markdown into blocks and validates blocks.
It makes no judgement calls about content: it reports, Claude decides.
"""

import os
import re

from tools.parser import _latex_to_unicode
from tools.word_tool import _latex_to_omml, _normalize_stripped_latex

TEXT_TYPES = ("chapter", "heading2", "heading3", "body", "list_item")
ALL_TYPES = TEXT_TYPES + ("equation", "table", "figure")

DONE_MARKER = "[SECTION_WORKFLOW_COMPLETE]"

_HEADING_NUM_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,2})\.?\s+(.+?)\s*$")
_CHAPTER_PREFIX_RE = re.compile(r"^\s*chapter\s+\d+\s*[:.\-–—]?\s*", re.I)
_BOLD_HEADING_RE = re.compile(r"^\*\*\s*(\d+\.\d+(?:\.\d+)?)\.?\s+(.+?)\s*\*\*$")
_PLACEMENT_RE = re.compile(r"^\W*placement\s*:.*?(?:fig\.?|figure)\s*(\d+)", re.I)
_FIG_CAPTION_RE = re.compile(r"^\W*(?:fig\.?|figure)\s*(\d+)\s*[.:\-–—]\s*(.+?)\W*$", re.I)
_TABLE_CAPTION_RE = re.compile(r"^\W*table\s+(\d+)\s*[.:\-–—]\s*(.+?)\**\s*$", re.I)
_LIST_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

# Inline tokens, in priority order. Math first so * inside math is untouched.
INLINE_RE = re.compile(
    r"\$\$(?P<dmath>.+?)\$\$"
    r"|(?<!\\)\$(?P<math>[^$\n]+?)(?<!\\)\$"
    r"|\*\*\*(?P<bi>.+?)\*\*\*"
    r"|\*\*(?P<b>.+?)\*\*"
    r"|(?<![\w*])\*(?P<i>[^*\n]+?)\*(?![\w*])",
    re.S,
)


# ── Inline parsing ────────────────────────────────────────────────────────────

def inline_runs(text: str) -> list[dict]:
    """Split inline markdown into runs: {"text", "bold", "italic", "math"}."""
    runs: list[dict] = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            runs.append(_run(text[pos:m.start()]))
        if m.group("dmath") is not None or m.group("math") is not None:
            latex = (m.group("dmath") or m.group("math")).strip()
            runs.append({"text": latex, "bold": False, "italic": False, "math": True})
        elif m.group("bi") is not None:
            runs.append(_run(m.group("bi"), bold=True, italic=True))
        elif m.group("b") is not None:
            runs.append(_run(m.group("b"), bold=True))
        else:
            runs.append(_run(m.group("i"), italic=True))
        pos = m.end()
    if pos < len(text):
        runs.append(_run(text[pos:]))
    return [r for r in runs if r["text"]]


def _run(text: str, bold: bool = False, italic: bool = False) -> dict:
    return {"text": text.replace("\\$", "$"), "bold": bold, "italic": italic, "math": False}


def latex_to_omml(latex: str):
    """Convert LaTeX to an OMML element, or None. Tries the LaTeX as written
    first; only falls back to backslash reconstruction when that fails."""
    omml = _latex_to_omml(latex)
    if omml is None:
        omml = _latex_to_omml(_normalize_stripped_latex(latex))
    return omml


# ── Markdown → blocks ─────────────────────────────────────────────────────────

def markdown_to_blocks(md: str) -> list[dict]:
    """Convert ChatGPT markdown (as extracted by browser_tool) into blocks."""
    md = md.replace("\r\n", "\n").replace(DONE_MARKER, "")
    blocks: list[dict] = []
    pending_table_caption: tuple[int, str] | None = None

    for group in re.split(r"\n\s*\n", md.strip()):
        lines = [ln.rstrip() for ln in group.split("\n") if ln.strip()]
        if not lines:
            continue

        # Display equation: the whole group is one $$...$$ or \[...\]
        joined = "\n".join(lines).strip()
        eq = _display_equation(joined)
        if eq is not None:
            blocks.append({"type": "equation", "latex": eq})
            continue

        para: list[str] = []
        table_rows: list[list[str]] = []

        def flush_para():
            if para:
                blocks.append({"type": "body", "text": " ".join(s.strip() for s in para)})
                para.clear()

        def flush_table():
            nonlocal pending_table_caption
            if len(table_rows) == 1 and not pending_table_caption:
                # A lone tab-separated line is prose with a stray tab, not a table.
                blocks.append({"type": "body", "text": " ".join(table_rows[0])})
                table_rows.clear()
            if table_rows:
                num, cap = pending_table_caption or (0, "")
                blocks.append({
                    "type": "table",
                    "number": num,
                    "gpt_number": num,
                    "caption": cap,
                    "rows": [list(r) for r in table_rows],
                })
                table_rows.clear()
                pending_table_caption = None

        eq_lines: list[str] | None = None
        for line in lines:
            s = line.strip()

            # Display equation on its own line(s) inside a text group
            if eq_lines is not None:
                eq_lines.append(s)
                if s.endswith("$$"):
                    blocks.append({"type": "equation", "latex": "\n".join(eq_lines).strip()[2:-2].strip()})
                    eq_lines = None
                continue
            if s.startswith("$$") and s.count("$$") == 1:
                flush_para()
                eq_lines = [s]
                continue
            if s.startswith("$$") and s.endswith("$$") and s.count("$$") == 2 and len(s) > 4:
                flush_para()
                blocks.append({"type": "equation", "latex": s[2:-2].strip()})
                continue

            if _is_table_row(s):
                flush_para()
                if not _TABLE_SEP_RE.match(s):
                    table_rows.append(_split_table_row(s))
                continue
            flush_table()

            if _HR_RE.match(s):
                flush_para()
                continue

            heading = _heading(s)
            if heading:
                flush_para()
                blocks.append(heading)
                continue

            m = _PLACEMENT_RE.match(s)
            if m:
                flush_para()
                n = int(m.group(1))
                blocks.append({"type": "figure", "number": n, "gpt_number": n, "caption": "", "image": ""})
                continue

            m = _FIG_CAPTION_RE.match(s)
            if m and len(s) < 400:
                flush_para()
                _attach_figure_caption(blocks, int(m.group(1)), m.group(2).strip() + ".")
                continue

            m = _TABLE_CAPTION_RE.match(s)
            if m and len(s) < 300:
                flush_para()
                pending_table_caption = (int(m.group(1)), m.group(2).strip().strip("*").strip())
                continue

            m = _LIST_RE.match(s)
            if m and not s.startswith("**"):
                flush_para()
                blocks.append({"type": "list_item", "text": m.group(1).strip()})
                continue

            para.append(s)

        flush_para()
        flush_table()

    if pending_table_caption:
        blocks.append({"type": "body", "text": f"Table caption with no table: Table {pending_table_caption[0]}. {pending_table_caption[1]}"})
    return blocks


def _display_equation(text: str) -> str | None:
    if text.startswith("$$") and text.endswith("$$") and text.count("$$") == 2:
        return text[2:-2].strip()
    if text.startswith("\\[") and text.endswith("\\]"):
        return text[2:-2].strip()
    return None


def _is_table_row(s: str) -> bool:
    return "\t" in s or (s.startswith("|") and s.count("|") >= 2)


def _split_table_row(s: str) -> list[str]:
    if "\t" in s:
        cells = s.split("\t")
    else:
        cells = s.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _heading(s: str) -> dict | None:
    level = 0
    text = s
    m = re.match(r"^(#{1,6})\s+(.+)$", s)
    if m:
        level = len(m.group(1))
        text = m.group(2).strip().strip("*").strip()
    else:
        m = _BOLD_HEADING_RE.match(s)
        if not m:
            return None
        text = f"{m.group(1)} {m.group(2)}"

    if level == 1 and _CHAPTER_PREFIX_RE.match(text):
        return {"type": "chapter", "text": _CHAPTER_PREFIX_RE.sub("", text).strip()}

    num_m = _HEADING_NUM_RE.match(text)
    if num_m and "." in num_m.group(1):
        num, title = num_m.group(1), num_m.group(2).strip()
        depth = num.count(".")
        return {"type": "heading2" if depth == 1 else "heading3", "num": num, "text": title}

    if level == 1:
        return {"type": "chapter", "text": text}
    if level in (2, 3):
        return {"type": f"heading{level}", "num": "", "text": text}
    return {"type": "heading3", "num": "", "text": text}


def _attach_figure_caption(blocks: list[dict], number: int, caption: str):
    for b in reversed(blocks):
        if b["type"] == "figure" and b.get("number") == number and not b.get("caption"):
            b["caption"] = caption
            return
    blocks.append({"type": "figure", "number": number, "gpt_number": number, "caption": caption, "image": ""})


# ── Validation ────────────────────────────────────────────────────────────────

_CHATTER_RE = re.compile(
    r"let me know|shall i continue|would you like|is now complete|here is (?:the|section)|"
    r"continue to the next section|as an ai\b|i hope this|feel free to|"
    r"\[section_workflow_complete\]|^(?:certainly|sure|absolutely)[!,.]",
    re.I,
)
_LEFTOVER_MD_RE = re.compile(r"\*\*|^#{1,6}\s|\|\s*-{3,}|\t")
_PLACEHOLDER_RE = re.compile(r"placement\s*:|\[\s*(?:fig\.?|figure)\s*\d+\s*\]|KEEP\s*TOKEN\s*\d+", re.I)
_PROSE_UNICODE_MATH_RE = re.compile(r"[∑∏∫∈∉⊂⊆≤≥≠≈→←⇒×÷√∞∂∇αβγδεθλμσφω]")
_EQ_REF_RE = re.compile(r"\b(?:equations?|eqs?\.?)\s*\(?\s*\d+(?:\.\d+)*\s*\)?", re.I)
_FIG_REF_RE = re.compile(r"\b(?:figures?|figs?\.)\s*(\d+)\b", re.I)
_TABLE_REF_RE = re.compile(r"\btables?\s+(\d+)\b", re.I)
_REPEATED_WORD_RE = re.compile(r"\b(\w{2,})\s+\1\b", re.I)
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\w\s+[,.;:!?](?!\d)")


def _strip_math(text: str) -> str:
    return INLINE_RE.sub(lambda m: "X" if (m.group("dmath") or m.group("math")) else m.group(0), text)


def validate_blocks(blocks: list[dict]) -> dict:
    """Return {"errors": [...], "warnings": [...], "stats": {...}}.

    Errors block writing to Word. Warnings are for Claude to judge.
    """
    errors: list[str] = []
    warnings: list[str] = []
    stats = {t: 0 for t in ALL_TYPES}
    stats["inline_math"] = 0
    seen_headings: dict[str, int] = {}
    last_num: tuple = ()

    if not isinstance(blocks, list) or not blocks:
        return {"errors": ["No blocks."], "warnings": [], "stats": stats}

    for i, b in enumerate(blocks):
        where = f"block {i}"
        t = b.get("type")
        if t not in ALL_TYPES:
            errors.append(f"{where}: unknown type {t!r}")
            continue
        stats[t] += 1

        # A LaTeX command written with one backslash in JSON ("\rho", "\theta",
        # "\frac") is read as a control character plus the rest of the word.
        for key in ("text", "latex", "caption"):
            val = b.get(key)
            if isinstance(val, str) and re.search(r"[\x00-\x08\x0b-\x1f\t]", val):
                errors.append(f"{where}: control character in {key} (broken JSON escape such as "
                              f"\\rho or \\theta written with a single backslash?)")

        if t in TEXT_TYPES:
            text = (b.get("text") or "").strip()
            if not text:
                errors.append(f"{where} ({t}): empty text")
                continue
            where = f"{where} ({t}: {text[:50]!r})"
            _check_text(text, where, t, errors, warnings, stats)

            if t in ("heading2", "heading3", "chapter"):
                key = text.lower()
                if key in seen_headings:
                    warnings.append(f"{where}: duplicate heading (also block {seen_headings[key]})")
                seen_headings[key] = i
                num = b.get("num") or ""
                if num:
                    parts = tuple(int(p) for p in num.split("."))
                    if last_num and parts < last_num:
                        warnings.append(f"{where}: heading number {num} goes backwards")
                    last_num = parts

        elif t == "equation":
            latex = (b.get("latex") or "").strip()
            if not latex:
                errors.append(f"{where} (equation): empty latex")
            elif latex_to_omml(latex) is None:
                errors.append(f"{where} (equation): LaTeX does not convert to a Word equation: {latex[:120]!r}")
            else:
                _check_latex_balance(latex, f"{where} (equation)", errors)
            if str(b.get("label") or "").strip():
                errors.append(f"{where} (equation): equations are not numbered in this book; remove the label")

        elif t == "table":
            rows = b.get("rows") or []
            cap = (b.get("caption") or "").strip()
            if not cap:
                errors.append(f"{where} (table): missing caption")
            if not isinstance(b.get("number"), int) or b.get("number", 0) <= 0:
                errors.append(f"{where} (table {cap[:40]!r}): missing table number")
            if len(rows) < 2:
                errors.append(f"{where} (table {cap[:40]!r}): needs a header row and at least one data row")
                continue
            widths = {len(r) for r in rows}
            if len(widths) != 1:
                errors.append(f"{where} (table {cap[:40]!r}): rows have different column counts {sorted(widths)}")
            if any(not str(c).strip() for c in rows[0]):
                errors.append(f"{where} (table {cap[:40]!r}): empty header cell")
            empty = sum(1 for r in rows[1:] for c in r if not str(c).strip())
            if empty:
                warnings.append(f"{where} (table {cap[:40]!r}): {empty} empty data cell(s)")
            for r in rows:
                for c in r:
                    if "$" in str(c) or "**" in str(c):
                        warnings.append(f"{where} (table {cap[:40]!r}): cell has markdown/LaTeX that Word will show literally: {str(c)[:60]!r}")

        elif t == "figure":
            num = b.get("number")
            cap = (b.get("caption") or "").strip()
            img = b.get("image") or ""
            if not isinstance(num, int) or num <= 0:
                errors.append(f"{where} (figure): missing figure number")
            if not cap:
                errors.append(f"{where} (figure {num}): missing caption")
            if not img:
                errors.append(f"{where} (figure {num}): no image yet. Draw it with chatgpt_draw_figure")
            elif not os.path.exists(img):
                errors.append(f"{where} (figure {num}): image file not found: {img}")
            else:
                info = image_info(img)
                if info.get("error"):
                    errors.append(f"{where} (figure {num}): image unreadable: {info['error']}")
                elif min(info["width"], info["height"]) < 300:
                    warnings.append(f"{where} (figure {num}): low resolution {info['width']}x{info['height']}")

    figs = [b.get("number") for b in blocks if b.get("type") == "figure"]
    dupes = {n for n in figs if figs.count(n) > 1}
    if dupes:
        errors.append(f"figure number(s) used more than once: {sorted(dupes)}")

    return {"errors": errors, "warnings": warnings, "stats": stats}


def _check_text(text, where, t, errors, warnings, stats):
    for m in INLINE_RE.finditer(text):
        latex = m.group("dmath") or m.group("math")
        if latex is None:
            continue
        stats["inline_math"] += 1
        if latex_to_omml(latex.strip()) is None:
            errors.append(f"{where}: inline math does not convert: {latex[:80]!r}")

    prose = _strip_math(text)
    if len(re.findall(r"(?<!\\)\$", prose)) % 2:
        errors.append(f"{where}: unbalanced $ delimiter")
    if _LEFTOVER_MD_RE.search(INLINE_RE.sub(" ", text)):
        errors.append(f"{where}: leftover markdown")
    if _PLACEHOLDER_RE.search(prose):
        errors.append(f"{where}: placeholder / placement text in prose")
    if _CHATTER_RE.search(prose):
        errors.append(f"{where}: ChatGPT meta-commentary")
    m = _EQ_REF_RE.search(prose)
    if m:
        errors.append(f"{where}: numbered equation reference {m.group(0)!r}; equations are unnumbered, "
                      "refer to it by position (e.g. 'the equation above')")
    if t == "body":
        if not re.search(r"[.!?:)\"'”’]$", text.strip()):
            warnings.append(f"{where}: paragraph does not end with punctuation (truncated?)")
        if _PROSE_UNICODE_MATH_RE.search(prose):
            warnings.append(f"{where}: Unicode math symbol outside $...$")
        for m in _REPEATED_WORD_RE.finditer(prose):
            if m.group(1).lower() not in ("that", "had"):
                warnings.append(f"{where}: repeated word {m.group(0)!r}")
        if _SPACE_BEFORE_PUNCT_RE.search(prose):
            warnings.append(f"{where}: space before punctuation")
        if "  " in prose:
            warnings.append(f"{where}: double space")


def _check_latex_balance(latex: str, where: str, errors: list[str]):
    depth = 0
    i = 0
    while i < len(latex):
        ch = latex[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                break
        i += 1
    if depth != 0:
        errors.append(f"{where}: unbalanced braces in {latex[:80]!r}")
    if len(re.findall(r"\\left\b", latex)) != len(re.findall(r"\\right\b", latex)):
        errors.append(f"{where}: \\left/\\right count mismatch in {latex[:80]!r}")
    begins = re.findall(r"\\begin\{(\w+\*?)\}", latex)
    ends = re.findall(r"\\end\{(\w+\*?)\}", latex)
    if sorted(begins) != sorted(ends):
        errors.append(f"{where}: \\begin/\\end mismatch in {latex[:80]!r}")


def image_info(path: str) -> dict:
    import hashlib
    try:
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        with open(path, "rb") as f:
            sha1 = hashlib.sha1(f.read()).hexdigest()
        return {"width": w, "height": h, "sha1": sha1}
    except Exception as exc:
        return {"error": str(exc)}


def unicode_fallback(latex: str) -> str:
    return _latex_to_unicode(latex)


def check_numbering(blocks: list[dict], next_figure: int, next_table: int) -> list[str]:
    """Caption numbers in the text must equal the numbers Word will assign.

    Word numbers captions itself (SEQ fields), so figures in this unit must be
    next_figure, next_figure+1, ... in order, and likewise tables. A gap means
    something was dropped; a repeat means something is duplicated. Prose may
    only reference figures/tables that exist once this unit is written.
    """
    errors: list[str] = []
    figs = [b.get("number") for b in blocks if b.get("type") == "figure"]
    tables = [b.get("number") for b in blocks if b.get("type") == "table"]
    want_f = list(range(next_figure, next_figure + len(figs)))
    want_t = list(range(next_table, next_table + len(tables)))
    if figs != want_f:
        errors.append(f"figure numbers {figs} but Word will number them {want_f}. "
                      "A gap means a figure was dropped: find it before writing.")
    if tables != want_t:
        errors.append(f"table numbers {tables} but Word will number them {want_t}. "
                      "A gap means a table was dropped: find it before writing.")
    last_f = next_figure + len(figs) - 1
    last_t = next_table + len(tables) - 1
    for i, b in enumerate(blocks):
        if b.get("type") not in TEXT_TYPES:
            continue
        prose = _strip_math(b.get("text", ""))
        for m in _FIG_REF_RE.finditer(prose):
            if int(m.group(1)) > last_f:
                errors.append(f"block {i}: refers to {m.group(0)!r} but the last figure will be {last_f}")
        for m in _TABLE_REF_RE.finditer(prose):
            if int(m.group(1)) > last_t:
                errors.append(f"block {i}: refers to {m.group(0)!r} but the last table will be {last_t}")
    return errors
