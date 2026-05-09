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
FIGURE_PLACEMENT_RE = re.compile(
    r"^\s*placement\s*:\s*(?:insert\s+)?(?:fig\.?|figure)\s*(\d+)\s*(?:here\.?)?\s*$", re.I
)
FIGURE_CAPTION_RE = re.compile(
    r"^\s*(?:fig\.?|figure)\s+(\d+)[.]\s+(.+)$", re.I
)


@dataclass
class Run:
    text: str
    bold: bool = False
    italic: bool = False


@dataclass
class Block:
    block_type: str  # 'chapter','heading2','heading3','body','list_item','artifact','table','equation','figure_placeholder','figure_caption','figure'
    runs: List[Run] = field(default_factory=list)
    table_rows: List[List[str]] = field(default_factory=list)  # rows × cols for 'table' blocks
    latex: str = ""           # raw LaTeX string for 'equation' blocks
    figure_number: int = 0    # figure number for figure_* blocks
    figure_image_path: str = ""  # local image path for 'figure' blocks

    @property
    def plain_text(self) -> str:
        return "".join(r.text for r in self.runs)


def parse_inline(text: str) -> List[Run]:
    """Split inline markdown (***bold+italic***, **bold**, *italic*) into Runs.
    Inline $$latex$$ is rendered as italic text (the LaTeX expression, no markers)."""
    runs: List[Run] = []
    pattern = re.compile(
        r"(\*{3}(.+?)\*{3}|\*{2}(.+?)\*{2}|\*(.+?)\*|\$\$(.+?)\$\$|([^*$]+))"
    )
    for match in pattern.finditer(text):
        if match.group(2):
            runs.append(Run(match.group(2), bold=True, italic=True))
        elif match.group(3):
            runs.append(Run(match.group(3), bold=True))
        elif match.group(4):
            runs.append(Run(match.group(4), italic=True))
        elif match.group(5):  # inline $$...$$
            runs.append(Run(match.group(5), italic=True))
        elif match.group(6):
            runs.append(Run(match.group(6)))
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
    Lines before the first tab line are treated as a caption (artifact block).
    Tab lines become a single 'table' block with structured row/column data.
    """
    result: List[Block] = []

    first_tab = next((i for i, line in enumerate(lines) if "\t" in line), len(lines))
    caption_lines = lines[:first_tab]
    table_lines = lines[first_tab:]

    if caption_lines:
        _append_artifact_from_lines(result, caption_lines)

    rows = [
        [cell.strip() for cell in line.split("\t")]
        for line in table_lines
        if "\t" in line
    ]
    if rows:
        block = Block(block_type="table")
        block.table_rows = rows
        result.append(block)

    return result


def _is_figure_placement(lines: List[str]) -> bool:
    return bool(lines and FIGURE_PLACEMENT_RE.match(lines[0]))


def _parse_figure_placement(lines: List[str]) -> Block:
    m = FIGURE_PLACEMENT_RE.match(lines[0])
    b = Block("figure_placeholder")
    b.figure_number = int(m.group(1))
    return b


def _is_figure_caption(lines: List[str]) -> bool:
    return bool(lines and FIGURE_CAPTION_RE.match(_strip_inline_markers(lines[0])))


def _parse_figure_caption(lines: List[str]) -> List[Block]:
    result: List[Block] = []
    m = FIGURE_CAPTION_RE.match(_strip_inline_markers(lines[0]))
    b = Block("figure_caption")
    b.figure_number = int(m.group(1))
    b.runs = parse_inline(lines[0].strip())
    result.append(b)
    if len(lines) > 1:
        _append_artifact_from_lines(result, lines[1:])
    return result


def _is_display_equation(lines: List[str]) -> bool:
    """True when the group is a single $$latex$$ block."""
    if len(lines) == 1:
        s = lines[0].strip()
        return s.startswith("$$") and s.endswith("$$") and len(s) > 4
    # Multi-line: $$ on first line, $$ on last line
    return lines[0].strip() == "$$" and lines[-1].strip() == "$$" and len(lines) >= 3


def _parse_display_equation(lines: List[str]) -> Block:
    if len(lines) == 1:
        latex = lines[0].strip()[2:-2].strip()
    else:
        latex = "\n".join(lines[1:-1]).strip()
    b = Block("equation")
    b.latex = latex
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

        elif _is_figure_placement(lines):
            blocks.append(_parse_figure_placement(lines))

        elif _is_figure_caption(lines):
            blocks.extend(_parse_figure_caption(lines))

        elif _is_non_prose_group(lines):
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

            else:
                _append_body_from_lines(blocks, lines)

    return blocks
