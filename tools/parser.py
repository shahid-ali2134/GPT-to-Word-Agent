"""
Parses ChatGPT's markdown response into structured blocks that can be mapped to
Word document styles.
"""

import re
from dataclasses import dataclass, field
from typing import List, Tuple

HEADING3_NUMBER_RE = re.compile(r"^\s*\d+\.\d+\.\d+\.?\s+(.+?)\s*$")
HEADING2_NUMBER_RE = re.compile(r"^\s*\d+\.\d+\.?\s+(.+?)\s*$")
CHAPTER_NUMBER_RE = re.compile(r"^\s*chapter\s+\d+\.?\s*$", re.I)
NON_PROSE_START_RE = re.compile(
    r"^\s*(table\s+\d+|fig\.?\s+\d+|figure\s+\d+|placement\s*:|equation\s+\d*)",
    re.I,
)
_INLINE_MARKER_RE = re.compile(r"^[\*_]{1,3}|[\*_]{1,3}$")
# Finds any "Fig. X" / "Figure X" reference in free-form text
_FIGURE_REF_RE = re.compile(r"\b(?:fig\.?|figure)\s*(\d+)\b", re.I)

# Line that explicitly says where to put a figure
_PLACEMENT_LINE_RE = re.compile(r"^\s*placement\s*:", re.I)

# Line that starts with a figure label and a separator ("Fig. 11." / "Figure 11:" / "Fig 11 –")
_FIGURE_LABEL_START_RE = re.compile(
    r"^\s*(?:fig\.?|figure)\s+(\d+)\s*[.:\-–—]", re.I
)

# Standalone "Table X. Title" / "Table X: Title" — separator is REQUIRED to avoid
# matching prose like "Table 1 shows that..." as a caption.
_TABLE_TITLE_RE = re.compile(r"^\s*table\s+\d+\s*[.:\-–—]\s*\S", re.I)
# Strip "Table X." / "Table X:" prefix so Word's auto-number isn't duplicated
_TABLE_LABEL_PREFIX_RE = re.compile(r"^\s*table\s+\d+\s*[.:\-–—]?\s*", re.I)

# Detects a raw LaTeX equation that GPT emitted without $$ markers.
# Must contain at least one \command and look like "expr = ..." or start with \command.
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+")
_STANDALONE_EQ_START_RE = re.compile(
    r"^[A-Za-z_{}^\\()\[\]\d\s,.]+\s*="   # expression = ...
    r"|^\\[a-zA-Z]"                         # starts with \command
)
_LATEX_TAG_STRIP_RE = re.compile(
    r"\\tag\*?\{[^}]*\}|\\label\{[^}]*\}|\\notag\b|\\nonumber\b",
    re.IGNORECASE,
)

# Unicode characters that signal a mathematical formula (not found in normal prose)
_MATH_UNICODE_RE = re.compile(
    r"[∑∏∫∬∭∮∧∨∀∃∄∈∉∋⊂⊃⊆⊇⊕⊗⊙⊘∓√∞∂∇≡≅≃≈∼≜≥≤≠ℝℕℤℚℂℙ𝔼𝟙𝟘]"
)
# Common prose function words — their presence signals a sentence, not a formula
_PROSE_WORD_RE = re.compile(
    r"\b(the|a|an|is|are|was|were|be|been|have|has|to|of|in|on|at|for|with|by)\b",
    re.I,
)

# Common LaTeX commands → Unicode for inline symbol rendering in Word
_LATEX_UNICODE = {
    r"\alpha": "α",   r"\beta": "β",    r"\gamma": "γ",   r"\delta": "δ",
    r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
    r"\theta": "θ",   r"\vartheta": "ϑ", r"\iota": "ι",  r"\kappa": "κ",
    r"\lambda": "λ",  r"\mu": "μ",      r"\nu": "ν",      r"\xi": "ξ",
    r"\pi": "π",      r"\varpi": "ϖ",   r"\rho": "ρ",     r"\varrho": "ϱ",
    r"\sigma": "σ",   r"\varsigma": "ς", r"\tau": "τ",    r"\upsilon": "υ",
    r"\phi": "φ",     r"\varphi": "φ",  r"\chi": "χ",     r"\psi": "ψ",
    r"\omega": "ω",
    r"\Gamma": "Γ",   r"\Delta": "Δ",   r"\Theta": "Θ",   r"\Lambda": "Λ",
    r"\Xi": "Ξ",      r"\Pi": "Π",      r"\Sigma": "Σ",   r"\Upsilon": "Υ",
    r"\Phi": "Φ",     r"\Psi": "Ψ",     r"\Omega": "Ω",
    r"\leq": "≤",     r"\geq": "≥",     r"\neq": "≠",     r"\approx": "≈",
    r"\infty": "∞",   r"\partial": "∂", r"\nabla": "∇",   r"\sum": "∑",
    r"\prod": "∏",    r"\int": "∫",     r"\in": "∈",      r"\notin": "∉",
    r"\subset": "⊂",  r"\subseteq": "⊆", r"\cup": "∪",   r"\cap": "∩",
    r"\forall": "∀",  r"\exists": "∃",  r"\neg": "¬",     r"\wedge": "∧",
    r"\vee": "∨",     r"\oplus": "⊕",   r"\otimes": "⊗",  r"\cdot": "·",
    r"\times": "×",   r"\div": "÷",     r"\pm": "±",      r"\mp": "∓",
    r"\rightarrow": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
    r"\Leftarrow": "⇐", r"\leftrightarrow": "↔", r"\Leftrightarrow": "⟺",
    r"\to": "→",      r"\gets": "←",
}


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class Block:
    block_type: str  # 'chapter','heading2','heading3','body','list_item','artifact','table','table_caption','equation','figure_placeholder','figure_caption','figure'
    runs: List[Run] = field(default_factory=list)
    table_rows: List[List[str]] = field(default_factory=list)  # rows × cols for 'table' blocks
    latex: str = ""           # raw LaTeX string for 'equation' blocks
    figure_number: int = 0    # figure number for figure_* blocks
    figure_image_path: str = ""  # local image path for 'figure' blocks

    @property
    def plain_text(self) -> str:
        return "".join(r.text for r in self.runs)


def _latex_to_unicode(text: str) -> str:
    """Replace known LaTeX commands with their Unicode equivalents."""
    # Subscripts: x_{abc} or x_a  →  x (subscript chars not available in plain Unicode,
    # so strip the braces and leave the content; e.g. \lambda_{1} → λ₁ where possible)
    # First expand known \commands
    for cmd, uni in _LATEX_UNICODE.items():
        text = text.replace(cmd, uni)
    # Strip remaining \commands (unknown ones) — remove the backslash so \exec → exec
    text = re.sub(r"\\([a-zA-Z]+)", r"\1", text)
    # Remove braces used for grouping: {abc} → abc
    text = re.sub(r"\{([^{}]*)\}", r"\1", text)
    # Convert subscript digits: x_1 → x₁  (only single digits)
    _SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
    text = re.sub(r"_(\d)", lambda m: m.group(1).translate(_SUB), text)
    # Strip remaining _ and ^
    text = text.replace("_", "").replace("^", "")
    return text.strip()


def parse_inline(text: str) -> List[Run]:
    """Split inline markdown and math tokens into Runs.

    Handles (in priority order):
      ***bold+italic***  **bold**  *italic*
      $$latex$$  — double-dollar inline/display math  → Unicode italic run
      $latex$    — single-dollar inline math          → Unicode italic run
      plain text
    """
    runs: List[Run] = []
    pattern = re.compile(
        r"(\*{3}(.+?)\*{3}"          # group 1/2  ***bold+italic***
        r"|\*{2}(.+?)\*{2}"          # group 3    **bold**
        r"|\*(.+?)\*"                 # group 4    *italic*
        r"|\$\$(.+?)\$\$"            # group 5    $$latex$$
        r"|\$([^$\n]+?)\$"           # group 6    $latex$  (no newline inside)
        r"|([^*$]+))",               # group 7    plain text
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        if match.group(2):
            runs.append(Run(match.group(2), bold=True, italic=True))
        elif match.group(3):
            runs.append(Run(match.group(3), bold=True))
        elif match.group(4):
            runs.append(Run(match.group(4), italic=True))
        elif match.group(5):  # $$latex$$ → Unicode italic
            runs.append(Run(_latex_to_unicode(match.group(5)), italic=True))
        elif match.group(6):  # $latex$ → Unicode italic
            runs.append(Run(_latex_to_unicode(match.group(6)), italic=True))
        elif match.group(7):
            runs.append(Run(match.group(7)))
    return runs if runs else [Run(text)]


def _strip_numbered_heading(text: str) -> Tuple[str | None, str]:
    """Return heading type and title for lines like '2.1 Title'."""
    heading3 = HEADING3_NUMBER_RE.match(text)
    if heading3:
        return "heading3", heading3.group(1).strip()

    heading2 = HEADING2_NUMBER_RE.match(text)
    if heading2:
        return "heading2", heading2.group(1).strip()

    return None, text.strip()


def _append_body_from_lines(blocks: List[Block], lines: List[str]):
    content = " ".join(line.strip() for line in lines if line.strip())
    if content:
        blocks.append(Block("body", parse_inline(content)))


def _split_body_and_equations(lines: List[str]) -> List[Block]:
    """
    Split a mixed paragraph group into alternating body and equation blocks.

    Handles the case where ChatGPT writes a display equation ($$...$$) in the
    same paragraph group as surrounding prose (no blank line separator).  Without
    this split, the whole group becomes one body block and the equation is garbled
    by parse_inline / _latex_to_unicode before reaching Word.
    """
    result: List[Block] = []
    body_buf: List[str] = []
    eq_buf: List[str] = []
    in_eq = False

    for line in lines:
        stripped = line.strip()

        # Single-line: $$...$$ — whole equation on one line
        if not in_eq and stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
            if body_buf:
                _append_body_from_lines(result, body_buf)
                body_buf = []
            b = Block("equation")
            b.latex = stripped[2:-2].strip()
            result.append(b)
            continue

        # Start of multi-line equation (opens with $$ but doesn't close on same line)
        if not in_eq and stripped.startswith("$$") and not stripped.endswith("$$"):
            if body_buf:
                _append_body_from_lines(result, body_buf)
                body_buf = []
            in_eq = True
            eq_buf = [stripped]
            continue

        # Inside a multi-line equation
        if in_eq:
            eq_buf.append(stripped)
            if stripped.endswith("$$"):
                result.append(_parse_display_equation(eq_buf))
                eq_buf = []
                in_eq = False
            continue

        # Regular prose line
        body_buf.append(line)

    # Flush any unclosed equation as body (shouldn't happen with well-formed input)
    if in_eq and eq_buf:
        body_buf.extend(eq_buf)
    if body_buf:
        _append_body_from_lines(result, body_buf)

    return result


def _strip_inline_markers(text: str) -> str:
    return _INLINE_MARKER_RE.sub("", text).strip()


def _is_non_prose_group(lines: List[str]) -> bool:
    if not lines:
        return False
    if NON_PROSE_START_RE.match(_strip_inline_markers(lines[0])):
        return True
    if len(lines) > 1 and any("\t" in line for line in lines):
        return True
    if len(lines) > 1 and sum(1 for line in lines if "|" in line) >= 2:
        return True
    return False


def _append_artifact_from_lines(blocks: List[Block], lines: List[str]):
    content = "\n".join(line.strip() for line in lines if line.strip())
    if content:
        blocks.append(Block("artifact", parse_inline(content)))


def _is_table_group(lines: List[str]) -> bool:
    """True when at least two lines contain tab characters (header + one data row)."""
    return sum(1 for line in lines if "\t" in line) >= 2


def _parse_table_group(lines: List[str]) -> List[Block]:
    """
    Parse a group that contains tab-separated table rows.
    Lines before the first tab line become a table_caption block (written
    below the table in Word using Insert Caption style).
    Tab lines become a single 'table' block with structured row/column data.
    Non-tab lines after the last tab row (paragraph stuck to the table with
    no blank line) are emitted as body blocks so they are not silently dropped.
    """
    result: List[Block] = []

    first_tab = next((i for i, line in enumerate(lines) if "\t" in line), len(lines))
    caption_lines = lines[:first_tab]
    table_lines = lines[first_tab:]

    if caption_lines:
        content = " ".join(line.strip() for line in caption_lines if line.strip())
        if content:
            result.append(Block("table_caption", parse_inline(content)))

    rows = [
        [cell.strip() for cell in line.split("\t")]
        for line in table_lines
        if "\t" in line
    ]
    if rows:
        block = Block(block_type="table")
        block.table_rows = rows
        result.append(block)

    # Any non-tab lines after the last tab row (no blank line separator in the
    # original text) would otherwise be silently dropped — emit them as body.
    last_tab_idx = max((i for i, ln in enumerate(table_lines) if "\t" in ln), default=-1)
    trailing = [ln for ln in table_lines[last_tab_idx + 1:] if ln.strip()]
    if trailing:
        _append_body_from_lines(result, trailing)

    return result


def _extract_figure_number(text: str) -> int:
    """Return the first figure number found anywhere in *text*, or 0."""
    m = _FIGURE_REF_RE.search(text)
    return int(m.group(1)) if m else 0


def _is_figure_block(lines: List[str]) -> bool:
    """
    True when a group is primarily about a figure rather than prose.

    Catches all common GPT formats:
      • Placement instructions  – "Placement: Insert Fig. 11 near …"
      • Imperative placements   – "Insert Figure 12 here." / "Add Fig. 3 below."
      • Caption lines           – "Fig. 11. Title." / "Figure 11: Title."
      • Figure-only short lines – a single line that IS a figure reference
    Avoids matching inline prose that merely *mentions* a figure in passing.
    """
    if not lines:
        return False

    first = _strip_inline_markers(lines[0])

    # Explicit placement instruction
    if _PLACEMENT_LINE_RE.match(first):
        return True

    # Imperative: "Insert/Place/Add/Put Fig. X …"
    if re.search(r"\b(insert|place|put|add)\b", first, re.I) and _FIGURE_REF_RE.search(first):
        return True

    # Caption / label line – starts with "Fig. X." or "Figure X:" etc.
    if _FIGURE_LABEL_START_RE.match(first):
        return True

    # Short standalone line that is ONLY a figure reference
    # e.g. "Fig. 11" or "Figure 11 goes here." (≤ 10 words, contains fig ref)
    if _FIGURE_REF_RE.search(first) and len(first.split()) <= 10:
        return True

    return False


def _parse_figure_block(lines: List[str]) -> List[Block]:
    """
    Convert a figure-related group into one or more blocks.

    • Placement line           → figure_placeholder
    • Caption line (Fig. X.)   → figure_caption  (description lines → artifact)
    • Anything else with a ref → artifact (drawing instructions, skip in Word)
    """
    result: List[Block] = []
    first = _strip_inline_markers(lines[0])
    fig_num = _extract_figure_number(" ".join(lines))

    # ── Placement instruction ─────────────────────────────────────────────────
    is_placement = (
        _PLACEMENT_LINE_RE.match(first) or
        (re.search(r"\b(insert|place|put|add)\b", first, re.I) and fig_num)
    )
    if is_placement:
        if fig_num == 0:
            # "Placement:" line with no figure number — skip as artifact
            _append_artifact_from_lines(result, lines)
            return result
        b = Block("figure_placeholder")
        b.figure_number = fig_num
        result.append(b)
        if len(lines) > 1:
            _append_artifact_from_lines(result, lines[1:])
        return result

    # ── Caption line ──────────────────────────────────────────────────────────
    if _FIGURE_LABEL_START_RE.match(first):
        b = Block("figure_caption")
        b.figure_number = fig_num
        b.runs = parse_inline(lines[0].strip())
        result.append(b)
        if len(lines) > 1:
            _append_artifact_from_lines(result, lines[1:])
        return result

    # ── Description / instructions (skip in Word) ─────────────────────────────
    _append_artifact_from_lines(result, lines)
    return result


def _is_display_equation(lines: List[str]) -> bool:
    """True when the group is a $$latex$$ display equation block."""
    if len(lines) == 1:
        s = lines[0].strip()
        return s.startswith("$$") and s.endswith("$$") and len(s) > 4
    # Multi-line: $$ alone on first line AND alone on last line
    if lines[0].strip() == "$$" and lines[-1].strip() == "$$" and len(lines) >= 3:
        return True
    # Multi-line where $$ is inline on the first/last content line:
    #   $$P_{ij} = \left( ...     ← first line
    #   ... \right) \tag{45}$$   ← last line
    first, last = lines[0].strip(), lines[-1].strip()
    if first.startswith("$$") and last.endswith("$$"):
        return True
    return False


def _is_standalone_latex_equation(lines: List[str]) -> bool:
    """
    True when a group is a mathematical equation emitted without $$ markers.

    Catches three cases:
    1. Raw LaTeX  — contains \\command and looks expression-shaped
       e.g.  R = \\lambda_1 L + \\lambda_2 I \\tag{10}
    2. Rendered Unicode — GPT stripped backslashes but left Unicode operators
       e.g.  Vt = mathbb1[qt ≥ τq land pt = 1 land et ≥ τe] tag25
    3. Matrix / piecewise equations — may have stripped backslashes but are
       identified by alignment (&) and row-break (\\) markers, or by the
       presence of stripped matrix environment names.
    """
    if not lines or len(lines) > 12:
        return False
    text = " ".join(line.strip() for line in lines if line.strip())
    if len(text) > 1200:
        return False

    # Case 3 first (most specific): matrix / piecewise / alignment equations.
    # These are often long (failing the 300-char limit) and multi-line.
    # Identifies them by column separators (& …) and at least one matrix keyword
    # or row-break marker, starting with a variable-like token.
    has_col_sep  = " & " in text or "&" in text
    has_row_sep  = "\\\\" in text
    has_matrix_kw = any(kw in text.lower() for kw in (
        "beginmatrix", "begin{matrix}", "begin{pmatrix}", "begin{bmatrix}",
        "begin{align", "begin{cases", "begin{array",
        "endmatrix",   "end{matrix}",  "end{pmatrix}",  "end{bmatrix}",
        "end{align",   "end{cases}",   "end{array}",
        "left\\{", "left\\|", "left\\(",
    ))
    eq_start = bool(re.match(r"^[A-Za-z_\s\d(\\{]", text))
    if eq_start and (has_matrix_kw or (has_col_sep and has_row_sep)):
        return True

    # Remaining cases apply the original (tighter) length limits.
    if len(text) > 300:
        return False
    if len(lines) > 3:
        return False

    # Case 1: LaTeX backslash commands
    if _LATEX_CMD_RE.search(text) and _STANDALONE_EQ_START_RE.match(text):
        return True

    # Case 2: Unicode math operators present, has an = sign, and not prose
    if _MATH_UNICODE_RE.search(text) and "=" in text:
        word_count = len(text.split())
        prose_count = len(_PROSE_WORD_RE.findall(text))
        if word_count <= 35 and prose_count < 3:
            return True

    return False


def _parse_display_equation(lines: List[str]) -> Block:
    b = Block("equation")
    if len(lines) == 1:
        b.latex = lines[0].strip()[2:-2].strip()
    elif lines[0].strip() == "$$" and lines[-1].strip() == "$$":
        b.latex = "\n".join(lines[1:-1]).strip()
    else:
        # $$ inline on first/last line — strip the leading and trailing $$
        joined = "\n".join(line.strip() for line in lines)
        b.latex = joined[2:-2].strip()
    return b


def parse_markdown(text: str) -> List[Block]:
    """
    Parse a markdown string into blocks.

    Numbered section titles like '2.1 Title' become heading2 blocks, numbered
    subsection titles like '2.1.1 Title' become heading3 blocks, and the manual
    number is stripped so Word's heading numbering does not duplicate it.
    """
    blocks: List[Block] = []
    raw_groups = re.split(r"\n{2,}", text.strip())

    for group in raw_groups:
        lines = [line.rstrip() for line in group.split("\n") if line.strip()]
        if not lines:
            continue

        first = lines[0]
        rest = lines[1:]

        if _is_table_group(lines):
            blocks.extend(_parse_table_group(lines))

        elif _is_display_equation(lines):
            blocks.append(_parse_display_equation(lines))

        elif _is_figure_block(lines):
            blocks.extend(_parse_figure_block(lines))

        elif _is_non_prose_group(lines):
            first_clean = _strip_inline_markers(lines[0])
            if _TABLE_TITLE_RE.match(first_clean):
                # Standalone "Table X. Title" → table_caption (written below table)
                content = " ".join(line.strip() for line in lines if line.strip())
                content = _TABLE_LABEL_PREFIX_RE.sub("", content).strip()
                blocks.append(Block("table_caption", parse_inline(content)))
            else:
                _append_artifact_from_lines(blocks, lines)

        elif CHAPTER_NUMBER_RE.match(first) and rest:
            blocks.append(Block("chapter", parse_inline(rest[0].strip())))
            _append_body_from_lines(blocks, rest[1:])

        elif first.startswith("### "):
            heading_text = first[4:].strip()
            if NON_PROSE_START_RE.match(_strip_inline_markers(heading_text)):
                _append_artifact_from_lines(blocks, [heading_text] + rest)
            else:
                detected_type, content = _strip_numbered_heading(heading_text)
                block_type = detected_type if detected_type else "heading3"
                blocks.append(Block(block_type, parse_inline(content)))
                _append_body_from_lines(blocks, rest)

        elif first.startswith("## "):
            heading_text = first[3:].strip()
            if NON_PROSE_START_RE.match(_strip_inline_markers(heading_text)):
                _append_artifact_from_lines(blocks, [heading_text] + rest)
            else:
                detected_type, content = _strip_numbered_heading(heading_text)
                block_type = detected_type if detected_type else "heading2"
                blocks.append(Block(block_type, parse_inline(content)))
                _append_body_from_lines(blocks, rest)

        elif first.startswith("# "):
            content = first[2:].strip()
            if CHAPTER_NUMBER_RE.match(content) and rest:
                content = rest[0].strip()
                rest = rest[1:]
                blocks.append(Block("chapter", parse_inline(content)))
            else:
                # ChatGPT sometimes uses h1 for section headings — reclassify if numbered
                numbered_type, stripped = _strip_numbered_heading(content)
                if numbered_type:
                    blocks.append(Block(numbered_type, parse_inline(stripped)))
                else:
                    blocks.append(Block("chapter", parse_inline(content)))
            _append_body_from_lines(blocks, rest)

        else:
            numbered_heading_type, content = _strip_numbered_heading(first)
            if numbered_heading_type:
                blocks.append(Block(numbered_heading_type, parse_inline(content)))
                _append_body_from_lines(blocks, rest)

            elif re.match(r"^[-*•]\s", first) or re.match(r"^\d+\.\s", first):
                for line in lines:
                    content = re.sub(r"^[-*•]\s+|^\d+\.\s+", "", line.strip())
                    if content:
                        blocks.append(Block("list_item", parse_inline(content)))

            elif _is_standalone_latex_equation(lines):
                eq_block = Block("equation")
                eq_block.latex = _LATEX_TAG_STRIP_RE.sub(
                    "", " ".join(line.strip() for line in lines)
                ).strip()
                blocks.append(eq_block)

            else:
                # If any line contains $$, split into body + equation sub-blocks
                # so embedded display equations are not garbled by parse_inline.
                if any("$$" in ln for ln in lines):
                    blocks.extend(_split_body_and_equations(lines))
                else:
                    _append_body_from_lines(blocks, lines)

    return blocks
