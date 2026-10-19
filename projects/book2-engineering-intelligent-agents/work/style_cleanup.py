"""Whole-book style cleanup of the Word file (user's rules, 2026-10-15).

  export <docx> <out_dir>          one JSON per chapter: every body paragraph with
                                   its inline equations replaced by [[M1]], [[M2]] ...
  apply  <docx> <out_dir> [--dry-run]
                                   writes chNN.patches.json back into Word: the prose
                                   is replaced, the original equation objects are kept
  layout <docx> [--dry-run]        no blank line between a table and its caption, one
                                   blank line before every table and display equation
  scan   <docx>                    counts what the style rules forbid

Patches: [{"id": <paragraph id from the export>, "new": "<text with every [[Mk]] once>"}].
New inline math may be added as $latex$ (converted to a Word equation). Paragraphs
are matched by id AND by their exported text, so a stale patch is refused.
Back up the docx first; Word must be closed.
"""
import copy
import glob
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)

from docx import Document  # noqa: E402

from tools.blocks import latex_to_omml  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
PH = re.compile(r"\[\[M(\d+)\]\]")
NEW_MATH = re.compile(r"(?<!\\)\$([^$\n]+?)(?<!\\)\$")

CHECKS = {
    "first_person": r"\b(I|we|We|our|Our|ours|us|you|You|your|Your|yours|Let us|let us|let's|Let's)\b",
    "dash": r"[—–]|\s--\s",
    "contraction": r"\b(it|that|there|here|what|who|he|she|they|we|you|let)['’]s\b"
                   r"|\b\w+n['’]t\b|\b\w+['’](re|ve|ll|d|m)\b",
    "colon": r":",
    "semicolon": r";",
    "eq_number_ref": r"\(\d{1,3}\)|\b[Ee]q(uation|\.)\s*\(?\d",
    "mid_however": r"\w, however, \w",
    "plain_math": r"[≤≥≠∑∈×Α-Ωα-ω]|left\\\{|beginmatrix",
}


def style_of(p):
    st = p.find(W + "pPr/" + W + "pStyle")
    return st.get(W + "val") if st is not None else ""


def kind(el):
    if el.tag == W + "tbl":
        return "table"
    if el.tag != W + "p":
        return "other"
    s = style_of(el)
    text = "".join(t.text or "" for t in el.iter(W + "t")).strip()
    has_math = el.find(".//" + M + "oMath") is not None
    if "aption" in s:
        return "caption"
    if s.startswith("Heading") or s.lower().startswith("title"):
        return "heading"
    if el.find(".//" + W + "drawing") is not None:
        return "figure"
    if has_math and not text:
        return "equation"
    if not text and not has_math:
        return "blank"
    # Code listings (docx_writer._write_code): every run in Consolas; never humanized.
    fonts = [rf.get(W + "ascii") for rf in el.iter(W + "rFonts")]
    if fonts and all(f == "Consolas" for f in fonts):
        return "code"
    return "body"


def elements(doc):
    return [e for e in doc.element.body if e.tag in (W + "p", W + "tbl")]


def para_text(p):
    """Paragraph prose with [[Mk]] for each inline equation, plus the equations' text."""
    parts, maths = [], {}
    for el in p:
        if el.tag == W + "r":
            parts.append("".join(t.text or "" for t in el.iter(W + "t")))
        elif el.tag in (M + "oMath", M + "oMathPara"):
            k = len(maths) + 1
            maths[f"M{k}"] = "".join(t.text or "" for t in el.iter(M + "t"))
            parts.append(f"[[M{k}]]")
        elif el.tag == W + "hyperlink":
            parts.append("".join(t.text or "" for t in el.iter(W + "t")))
    return "".join(parts), maths


def flags(text):
    prose = PH.sub(" ", text)
    return [k for k, pat in CHECKS.items() if re.search(pat, prose)]


def export(docx, out_dir):
    doc = Document(docx)
    els = elements(doc)
    os.makedirs(out_dir, exist_ok=True)
    chapters, ch = {}, 0
    for i, el in enumerate(els):
        k = kind(el)
        if k == "heading" and style_of(el) in ("Heading1", "Heading 1") and para_text(el)[0].strip():
            ch += 1
        if ch == 0 or k not in ("heading", "body"):
            continue
        text, maths = para_text(el)
        entry = {"id": i, "kind": k, "text": text}
        if k == "body":
            if maths:
                entry["math"] = maths
            f = flags(text)
            if f:
                entry["flags"] = f
        chapters.setdefault(ch, []).append(entry)
    for ch, entries in chapters.items():
        path = os.path.join(out_dir, f"ch{ch:02d}.json")
        json.dump(entries, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        body = [e for e in entries if e["kind"] == "body"]
        print(f"ch{ch:02d}: {len(body)} body paragraphs, {sum(1 for e in body if e.get('flags'))} flagged")


def rebuild(p, new, maths_el):
    """Replace the paragraph's runs and equations with `new` (prose + [[Mk]] + $latex$)."""
    runs = [el for el in p if el.tag == W + "r"]
    rpr = None
    for r in runs:
        if "".join(t.text or "" for t in r.iter(W + "t")).strip():
            rpr = r.find(W + "rPr")
            break
    for el in list(p):
        if el.tag in (W + "r", M + "oMath", M + "oMathPara"):
            p.remove(el)

    def add_text(s):
        if not s:
            return
        r = p.makeelement(W + "r", {})
        if rpr is not None:
            r.append(copy.deepcopy(rpr))
        t = r.makeelement(W + "t", {})
        t.text = s
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        r.append(t)
        p.append(r)

    pos = 0
    tokens = re.compile(r"\[\[M(\d+)\]\]|(?<!\\)\$([^$\n]+?)(?<!\\)\$")
    for m in tokens.finditer(new):
        add_text(new[pos:m.start()])
        if m.group(1):
            p.append(maths_el[int(m.group(1)) - 1])
        else:
            omml = latex_to_omml(m.group(2))
            if omml is None:
                raise ValueError(f"cannot convert ${m.group(2)}$")
            p.append(omml)
        pos = m.end()
    add_text(new[pos:])


def apply(docx, out_dir, dry):
    doc = Document(docx)
    els = elements(doc)
    done = refused = 0
    for pf in sorted(glob.glob(os.path.join(out_dir, "ch*.patches.json"))):
        export_file = pf.replace(".patches.json", ".json")
        exported = {e["id"]: e for e in json.load(open(export_file, encoding="utf-8"))}
        for pt in json.load(open(pf, encoding="utf-8")):
            pid, new = pt["id"], pt["new"].strip()
            src = exported.get(pid)
            el = els[pid] if pid < len(els) else None
            if src is None or el is None or src["kind"] != "body":
                print(f"{os.path.basename(pf)} id {pid}: not a body paragraph; refused")
                refused += 1
                continue
            cur, _ = para_text(el)
            if cur != src["text"]:
                print(f"{os.path.basename(pf)} id {pid}: Word text changed since export; refused")
                refused += 1
                continue
            maths_el = [x for x in el if x.tag in (M + "oMath", M + "oMathPara")]
            used = sorted(int(n) for n in PH.findall(new))
            if used != list(range(1, len(maths_el) + 1)):
                print(f"{os.path.basename(pf)} id {pid}: equations [[Mk]] missing or repeated; refused")
                refused += 1
                continue
            try:
                rebuild(el, new, maths_el)
            except ValueError as e:
                print(f"{os.path.basename(pf)} id {pid}: {e}; refused")
                refused += 1
                continue
            done += 1
    print(f"patched {done} paragraph(s), refused {refused}")
    if not dry and done:
        doc.save(docx)


def layout(docx, dry):
    doc = Document(docx)
    changed = 0
    while True:
        els = elements(doc)
        ks = [kind(e) for e in els]
        fix = None
        for i, k in enumerate(ks):
            if k != "table":
                continue
            # caption below the table: drop blank lines between them
            if i + 2 < len(ks) and ks[i + 1] == "blank" and ks[i + 2] == "caption":
                fix = ("remove", els[i + 1])
                break
            # caption above the table: drop blank lines between them
            if i >= 2 and ks[i - 1] == "blank" and ks[i - 2] == "caption":
                fix = ("remove", els[i - 1])
                break
            first = i - 1 if ks[i - 1] == "caption" else i
            if ks[first - 1] not in ("blank", "heading"):
                fix = ("blank_before", els[first])
                break
        if fix is None:
            for i, k in enumerate(ks):
                if k == "equation" and i and ks[i - 1] not in ("blank", "equation", "heading"):
                    fix = ("blank_before", els[i])
                    break
                if k == "equation" and i + 1 < len(ks) and ks[i + 1] not in ("blank", "equation", "heading"):
                    fix = ("blank_before", els[i + 1])
                    break
        if fix is None:
            break
        if fix[0] == "remove":
            fix[1].getparent().remove(fix[1])
        else:
            fix[1].addprevious(fix[1].makeelement(W + "p", {}))
        changed += 1
    print(f"layout fixes: {changed}")
    if not dry and changed:
        doc.save(docx)


def scan(docx):
    doc = Document(docx)
    counts, ch = {}, 0
    for el in elements(doc):
        if kind(el) == "heading" and style_of(el) in ("Heading1", "Heading 1") and para_text(el)[0].strip():
            ch += 1
        if ch == 0 or kind(el) != "body":
            continue
        text = PH.sub(" ", para_text(el)[0])
        for k, pat in CHECKS.items():
            n = len(re.findall(pat, text))
            if n:
                counts[k] = counts.get(k, 0) + n
    print(json.dumps(counts, indent=1))


def check(patches_file):
    """Validate one chapter's patches without touching Word."""
    exported = {e["id"]: e for e in json.load(open(patches_file.replace(".patches.json", ".json"),
                                                   encoding="utf-8"))}
    patches = json.load(open(patches_file, encoding="utf-8"))
    bad, seen = 0, set()
    for pt in patches:
        pid, new = pt["id"], pt["new"]
        src = exported.get(pid)
        if src is None or src["kind"] != "body":
            print(f"id {pid}: not a body paragraph"); bad += 1; continue
        if pid in seen:
            print(f"id {pid}: patched twice"); bad += 1
        seen.add(pid)
        want = list(range(1, len(src.get("math", {})) + 1))
        if sorted(int(n) for n in PH.findall(new)) != want:
            print(f"id {pid}: needs each of {['[[M%d]]' % n for n in want]} exactly once"); bad += 1
        for m in NEW_MATH.finditer(PH.sub(" ", new)):
            if latex_to_omml(m.group(1)) is None:
                print(f"id {pid}: cannot convert ${m.group(1)}$"); bad += 1
        left = [f for f in flags(new) if f not in ("plain_math",)]
        if left:
            print(f"id {pid}: still has {left}: {new[:100]!r}")
    patched = {pt["id"] for pt in patches}
    for e in exported.values():
        if e["kind"] == "body" and e["id"] not in patched:
            left = [f for f in e.get("flags", []) if f != "plain_math"]
            if left:
                print(f"id {e['id']}: unpatched but flagged {left}")
    print(f"{len(patches)} patch(es), {bad} error(s)")


def changed_words(old, new):
    """Words of `old` that `new` replaced or dropped (punctuation and case ignored)."""
    import difflib
    tok = lambda s: re.findall(r"\[\[M\d+\]\]|\$[^$]+\$|[A-Za-z0-9'’-]+", s.lower())
    a, b = tok(old), tok(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"), len(a)


def diffstat(out_dir, limit):
    """Per patch: how many words changed. Patches above `limit` are listed for review."""
    total = over = 0
    for pf in sorted(glob.glob(os.path.join(out_dir, "ch*.patches.json"))):
        exported = {e["id"]: e for e in json.load(open(pf.replace(".patches.json", ".json"),
                                                       encoding="utf-8"))}
        for pt in json.load(open(pf, encoding="utf-8")):
            n, size = changed_words(exported[pt["id"]]["text"], pt["new"])
            total += 1
            if n > limit:
                over += 1
                print(f"{os.path.basename(pf)} id {pt['id']}: {n} of {size} words changed")
    print(f"{total} patch(es), {over} above {limit} changed words")


if __name__ == "__main__":
    if sys.argv[1] == "check":
        check(sys.argv[2])
        sys.exit(0)
    if sys.argv[1] == "diffstat":
        diffstat(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 6)
        sys.exit(0)
    cmd, docx = sys.argv[1], sys.argv[2]
    dry = "--dry-run" in sys.argv
    if cmd == "export":
        export(docx, sys.argv[3])
    elif cmd == "apply":
        apply(docx, sys.argv[3], dry)
    elif cmd == "layout":
        layout(docx, dry)
    elif cmd == "scan":
        scan(docx)
