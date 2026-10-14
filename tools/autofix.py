"""
Automatic repairs for blocks: the mechanical fixes that used to wait for a
person. Each fix is reported as one line so the orchestrator can tell the user.

Safe fixes (always applied):
- control characters from broken JSON escapes (\\rho -> CR + "ho") restored;
- equation labels and \\tag{} / \\label{} removed (equations are unnumbered);
- LaTeX that does not convert to a Word equation retried with normalized commands;
- ChatGPT wrappers (<text weight=...>), "Placement:" leftovers and chatter removed;
- curly quotes straightened, space before punctuation and double spaces removed.

Numbering (applied when figure/table numbers do not continue from Word's):
- figures and tables renumbered in order from Word's next numbers, and
  "Figure N" / "Table N" references in the unit's prose remapped to match.
"""

import re

from tools.blocks import latex_to_omml

# Only unmistakable chatter is deleted; anything vaguer is left to validation.
_CHATTER_RE = re.compile(
    r"continue to the next section|let me know|shall i continue|would you like|"
    r"i hope this|feel free to|\[section_workflow_complete\]|^(?:certainly|sure|absolutely)[!,.]",
    re.I)

_ESCAPES = {"\r": "\\r", "\t": "\\t", "\x0c": "\\f", "\x08": "\\b", "\x0b": "\\v", "\x07": "\\a"}
_CTRL_RE = re.compile(r"[\r\t\x0c\x08\x0b\x07]")
_MATH_SPAN_RE = re.compile(r"\$\$.+?\$\$|(?<!\\)\$[^$]+?(?<!\\)\$", re.S)
_TAG_RE = re.compile(r"\\(?:tag\*?|label)\s*\{[^{}]*\}")
_WRAPPER_RE = re.compile(r"</?text(?:\s+[^>]*)?>", re.I)
_PLACEMENT_LINE_RE = re.compile(r"^\W*placement\s*:", re.I)
_CURLY = {"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"}
_SPACE_PUNCT_RE = re.compile(r"(?<=[A-Za-z0-9)\]])\s+([,.;:!?])(?=\s|$)")
_REF_RE = {"figure": re.compile(r"\b(Figures?|Figs?\.)(\s+)(\d+)\b"),
           "table": re.compile(r"\b(Tables?)(\s+)(\d+)\b")}

# Commands the Word converter does not know, with equivalents it does.
_LATEX_NORMALIZE = [
    (re.compile(r"\\operatorname\*?\{([^{}]*)\}"), r"\\mathrm{\1}"),
    (re.compile(r"\\(?:text|textrm|textnormal)\{([^{}]*)\}"), r"\\mathrm{\1}"),
    (re.compile(r"\\textbf\{([^{}]*)\}"), r"\\mathbf{\1}"),
    (re.compile(r"\\textit\{([^{}]*)\}"), r"\\mathit{\1}"),
    (re.compile(r"\\[dt]frac"), r"\\frac"),
    (re.compile(r"\\displaystyle\s*"), ""),
    (re.compile(r"\\(?:left|right)\.\s*"), ""),
    (re.compile(r"\\[,;:!]\s*|\\quad\s*|\\qquad\s*"), " "),
    (re.compile(r"\\boldsymbol"), r"\\mathbf"),
]


def _restore_ctrl(s: str, latex: bool) -> tuple[str, int]:
    n = len(_CTRL_RE.findall(s))
    s = _CTRL_RE.sub(lambda m: _ESCAPES[m.group(0)], s)
    if latex:
        # "\neq", "\nabla" ... become a newline + "eq", "abla". Equations also hold
        # real line breaks, so restore only unmistakable command remainders.
        s, k = re.subn(r"\n(?=(?:abla|eq|eg|otin|exists|leq|geq|mid|olimits|onumber|ewline)(?![a-zA-Z]))",
                       r"\\n", s)
        n += k
    return s, n


def _fix_inline_ctrl(text: str) -> tuple[str, int]:
    total = 0

    def repl(m):
        nonlocal total
        s, n = _restore_ctrl(m.group(0), latex=True)
        total += n
        return s

    text = _MATH_SPAN_RE.sub(repl, text)
    # control characters outside math are never wanted in prose
    text, n = re.subn(r"[\r\x0c\x08\x0b\x07]", "", text)
    text, k = re.subn(r"\t", " ", text)
    return text, total + n + k


def _normalize_latex(latex: str) -> str:
    for pat, rep in _LATEX_NORMALIZE:
        latex = pat.sub(rep, latex)
    return re.sub(r"\s{2,}", " ", latex).strip()


def fix_blocks(blocks: list[dict], next_figure: int | None = None,
               next_table: int | None = None) -> tuple[list[dict], list[str]]:
    """Apply the automatic repairs. Returns (blocks, fixes)."""
    fixes: list[str] = []
    out: list[dict] = []
    for i, b in enumerate(blocks):
        t = b.get("type")
        where = f"block {i}"
        if t == "equation":
            latex = b.get("latex") or ""
            new, n = _restore_ctrl(latex, latex=True)
            if n:
                fixes.append(f"{where}: restored {n} broken LaTeX escape(s) in an equation")
            stripped = _TAG_RE.sub("", new).strip()
            if stripped != new or str(b.get("label") or "").strip():
                fixes.append(f"{where}: removed equation number/label (equations are unnumbered)")
                b.pop("label", None)
            new = stripped
            if new and latex_to_omml(new) is None:
                norm = _normalize_latex(new)
                if norm != new and latex_to_omml(norm) is not None:
                    fixes.append(f"{where}: equation did not convert to Word math; normalized "
                                 f"unsupported commands so it does")
                    new = norm
            b["latex"] = new
        if t in ("body", "list_item", "heading2", "heading3", "chapter"):
            text = b.get("text") or ""
            new, n = _fix_inline_ctrl(text)
            if n:
                fixes.append(f"{where}: restored {n} broken escape(s) / control character(s)")
            if _WRAPPER_RE.search(new):
                new = _WRAPPER_RE.sub("", new)
                fixes.append(f"{where}: removed ChatGPT <text> wrapper")
            curly = sum(new.count(c) for c in _CURLY)
            if curly:
                for c, s in _CURLY.items():
                    new = new.replace(c, s)
                fixes.append(f"{where}: straightened {curly} curly quote(s)")
            parts = re.split(r"(\$\$.+?\$\$|(?<!\\)\$[^$]+?(?<!\\)\$)", new, flags=re.S)
            for k, part in enumerate(parts):
                if part.startswith("$"):
                    continue
                if k > 0:  # right after inline math: "$x$ , and" -> "$x$, and"
                    part = re.sub(r"^\s+([,.;:!?])(?=\s|$)", r"\1", part)
                parts[k] = re.sub(r" {2,}", " ", _SPACE_PUNCT_RE.sub(r"\1", part))
            spaced = "".join(parts)
            if spaced != new:
                fixes.append(f"{where}: removed stray spaces before punctuation")
                new = spaced
            new = new.strip()
            if t == "body" and (not new or _PLACEMENT_LINE_RE.match(new)
                                or (len(new) < 120 and _CHATTER_RE.search(new))):
                fixes.append(f"{where}: removed leftover ChatGPT line {new[:60]!r}")
                continue
            b["text"] = new
        if t in ("table", "figure"):
            cap = b.get("caption") or ""
            new, n = _fix_inline_ctrl(cap)
            for c, s in _CURLY.items():
                new = new.replace(c, s)
            if new != cap:
                fixes.append(f"{where}: cleaned {t} caption")
                b["caption"] = new
        out.append(b)

    if next_figure is not None or next_table is not None:
        fixes += _renumber(out, next_figure, next_table)
    return out, fixes


def _renumber(blocks: list[dict], next_figure, next_table) -> list[str]:
    fixes = []
    for kind, start in (("figure", next_figure), ("table", next_table)):
        if start is None:
            continue
        items = [b for b in blocks if b.get("type") == kind]
        expected = list(range(start, start + len(items)))
        if [b.get("number") for b in items] == expected:
            continue
        mapping = {}
        for b, n in zip(items, expected):
            old = b.get("number")
            src = b.get("gpt_number", old)
            if old != n:
                fixes.append(f"{kind} {old} renumbered to {n} (book-wide numbering continues from Word)")
            for key in {old, src}:
                if isinstance(key, int) and key != n:
                    mapping[key] = n
            b["number"] = n
        if mapping:
            pat = _REF_RE[kind]
            for b in blocks:
                if b.get("type") not in ("body", "list_item"):
                    continue
                new = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}{mapping.get(int(m.group(3)), int(m.group(3)))}",
                              b["text"])
                if new != b["text"]:
                    b["text"] = new
            fixes.append(f"{kind} references in the prose remapped: "
                         + ", ".join(f"{k}->{v}" for k, v in sorted(mapping.items())))
    return fixes
