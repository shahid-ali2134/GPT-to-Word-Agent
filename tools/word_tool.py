"""
Appends formatted content to a Word (.docx) document.
Parses ChatGPT's markdown output and applies the styles defined in config.json.
"""

import json
import os
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

from .parser import parse_markdown, Block, Run

PENDING_SUFFIX = ".pending.json"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

ALIGN_MAP = {
    "left":    WD_ALIGN_PARAGRAPH.LEFT,
    "center":  WD_ALIGN_PARAGRAPH.CENTER,
    "right":   WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}

STYLE_KEY_MAP = {
    "chapter":    "chapter",
    "heading2":   "heading2",
    "heading3":   "heading3",
    "body":       "body",
    "list_item":  "body",
    "artifact":   "body",
    "table":      "body",
}

WORD_STYLE_MAP = {
    "chapter":    "Heading 1",
    "heading2":   "Heading 2",
    "heading3":   "Heading 3",
    "body":       "Normal",
    "list_item":  "Normal",
    "artifact":   "Normal",
    "table":      "Normal",
}


def _load_styles() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f).get("styles", {})


def _apply_paragraph_format(para, cfg: dict):
    pf = para.paragraph_format
    if "alignment" in cfg:
        pf.alignment = ALIGN_MAP.get(cfg["alignment"], WD_ALIGN_PARAGRAPH.LEFT)
    if "space_before" in cfg:
        pf.space_before = Pt(cfg["space_before"])
    if "space_after" in cfg:
        pf.space_after = Pt(cfg["space_after"])
    if "first_line_cm" in cfg:
        pf.first_line_indent = Cm(cfg["first_line_cm"])
    if "hanging_cm" in cfg:
        pf.left_indent = Cm(cfg["hanging_cm"])
        pf.first_line_indent = Cm(-cfg["hanging_cm"])


def _apply_run_format(run, cfg: dict, bold: bool = False, italic: bool = False):
    run.font.name = cfg.get("font", "Garamond")
    run.font.size = Pt(cfg.get("size_pt", 11))
    run.bold = cfg.get("bold", False) or bold
    run.italic = italic
    if cfg.get("all_caps", False):
        run.font.all_caps = True


def _configure_page(doc: Document, page_cfg: dict):
    section = doc.sections[0]
    if "width_cm" in page_cfg:
        section.page_width = Cm(page_cfg["width_cm"])
    if "height_cm" in page_cfg:
        section.page_height = Cm(page_cfg["height_cm"])
    if "margin_cm" in page_cfg:
        m = Cm(page_cfg["margin_cm"])
        section.left_margin = section.right_margin = m
        section.top_margin = section.bottom_margin = m
    if "header_dist_cm" in page_cfg:
        section.header_distance = Cm(page_cfg["header_dist_cm"])
    if "footer_dist_cm" in page_cfg:
        section.footer_distance = Cm(page_cfg["footer_dist_cm"])


def _open_document(word_file_path: str, styles: dict) -> Document:
    if os.path.exists(word_file_path):
        return Document(word_file_path)

    doc = Document()
    page_cfg = styles.get("page", {})
    if page_cfg:
        _configure_page(doc, page_cfg)
    return doc


def _write_table_block(doc: Document, block, styles: dict):
    """Add a Word table for a 'table' block. First row is treated as header."""
    rows = block.table_rows
    if not rows:
        return
    num_cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=num_cols)
    table.style = "Table Grid"
    cfg = styles.get("body", {})
    font_name = cfg.get("font", "Garamond")
    font_size = Pt(cfg.get("size_pt", 11))

    for r_idx, row_data in enumerate(rows):
        is_header = r_idx == 0
        for c_idx, cell_text in enumerate(row_data):
            if c_idx >= num_cols:
                break
            cell = table.cell(r_idx, c_idx)
            cell.text = ""
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run(cell_text)
            run.font.name = font_name
            run.font.size = font_size
            run.bold = is_header

        # Fill any missing cells in this row
        for c_idx in range(len(row_data), num_cols):
            cell = table.cell(r_idx, c_idx)
            cell.text = ""
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run("")
            run.font.name = font_name
            run.font.size = font_size

    # Add a blank paragraph after the table so following text isn't flush
    doc.add_paragraph()


def append_blocks_to_word(blocks: list[Block], word_file_path: str) -> str:
    """Append pre-parsed blocks to the Word document using configured styles."""
    styles = _load_styles()
    doc = _open_document(word_file_path, styles)

    if not blocks:
        return "Warning: no content blocks parsed from response."

    for block in blocks:
        if block.block_type == "table":
            _write_table_block(doc, block, styles)
            continue

        style_key = STYLE_KEY_MAP.get(block.block_type, "body")
        word_style = WORD_STYLE_MAP.get(block.block_type, "Normal")
        cfg = styles.get(style_key, {})

        # Add the paragraph using the built-in Word style
        try:
            para = doc.add_paragraph(style=word_style)
        except KeyError:
            para = doc.add_paragraph()

        _apply_paragraph_format(para, cfg)

        # Bullet prefix for list items
        prefix = "• " if block.block_type == "list_item" else ""
        first_run = True
        for run_data in block.runs:
            text = (prefix + run_data.text) if first_run and prefix else run_data.text
            first_run = False
            if not text:
                continue
            run = para.add_run(text)
            _apply_run_format(run, cfg, bold=run_data.bold, italic=run_data.italic)

    doc.save(word_file_path)
    return f"OK: wrote {len(blocks)} block(s) to '{word_file_path}'"


def append_to_word(content: str, word_file_path: str) -> str:
    """
    Parse *content* and append it to the Word document at *word_file_path*,
    applying the configured styles. Creates the file if it does not exist.
    """
    return append_blocks_to_word(parse_markdown(content), word_file_path)


# ── Pending-file helpers ──────────────────────────────────────────────────────

def _pending_path(word_file_path: str) -> str:
    return word_file_path + PENDING_SUFFIX


def _blocks_to_json(blocks: list[Block]) -> list[dict]:
    return [
        {
            "block_type": b.block_type,
            "runs": [{"text": r.text, "bold": r.bold, "italic": r.italic} for r in b.runs],
            "table_rows": b.table_rows,
        }
        for b in blocks
    ]


def _blocks_from_json(data: list[dict]) -> list[Block]:
    result = []
    for entry in data:
        runs = [Run(text=r["text"], bold=r["bold"], italic=r["italic"]) for r in entry["runs"]]
        table_rows = entry.get("table_rows", [])
        result.append(Block(block_type=entry["block_type"], runs=runs, table_rows=table_rows))
    return result


def save_pending_blocks(blocks: list[Block], word_file_path: str):
    """Append *blocks* to the pending file for *word_file_path*."""
    path = _pending_path(word_file_path)
    existing: list[dict] = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.extend(_blocks_to_json(blocks))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def has_pending_blocks(word_file_path: str) -> bool:
    return os.path.exists(_pending_path(word_file_path))


def recover_pending_blocks(word_file_path: str) -> str:
    """
    Read the pending file for *word_file_path*, append its blocks to the
    Word document, and delete the pending file on success.
    """
    path = _pending_path(word_file_path)
    if not os.path.exists(path):
        return "No pending content found for this document."

    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    blocks = _blocks_from_json(raw)
    if not blocks:
        os.remove(path)
        return "Pending file was empty — nothing to recover."

    result = append_blocks_to_word(blocks, word_file_path)
    os.remove(path)
    return f"Recovered {len(blocks)} block(s). {result}"
