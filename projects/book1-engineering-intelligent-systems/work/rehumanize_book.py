"""Re-humanize a finished book's body text through StealthWriter (user, 2026-10-16).
Full procedure: .claude/skills/rehumanize-book/SKILL.md.

Only body prose is sent. Inline equations ([[Mk]]) and Figure/Table/Section/Chapter
references are locked as $...$ spans, which humanize_blocks swaps for KEEPTOKEN
placeholders, so StealthWriter never sees or changes them. Headings, captions,
tables, display equations and figures are never touched; style_cleanup.py apply
keeps the original Word equation objects.

  export <docx>               rehumanize/chNN.json for every chapter (style_cleanup export)
  prep   <NN> [words]         rehumanize/chNN.cK.blocks.json, one StealthWriter run each
                              (default 2,500 words per chunk)
  patch  <NN>                 rehumanize_apply/chNN.patches.json from all humanized chunks,
                              with the allowed mechanical fixes (dashes, contractions);
                              prints first-person hits to fix by hand (fewest words)
  mech   <NN> <docx>          the same mechanical fixes on the chapter as it is in Word now
  scantext <NN> <docx>        rehumanize/chNN.scan.txt: the chapter as in Word (math as
                              symbols) for stealthwriter_check_ai(text_file=...)
  stats                       words and paragraphs per chapter

Per chunk: humanize_blocks(project, "work/rehumanize/chNN.cK.blocks.json",
max_words_per_run=2500, max_tokens_per_paragraph=20) -> broken-sentence check ->
stealthwriter_alternatives / fewest-word fix in the chunk file -> next chunk.
Then patch, `python style_cleanup.py apply <docx> rehumanize_apply` (Word closed,
backup first), scantext + stealthwriter_check_ai.
"""
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "rehumanize")
APPLY = os.path.join(HERE, "rehumanize_apply")
PH = re.compile(r"\[\[M\d+\]\]")
REF = re.compile(
    r"\b(?:Figures?|Tables?|Sections?|Chapters?)\s+\d+(?:\.\d+)*"
    r"(?:(?:,\s*|\s+and\s+|\s+to\s+|\s+or\s+)\d+(?:\.\d+)*)*"
)
LOST_TOKEN = re.compile(r"k\w{0,5}\s*t\w{0,3}n\s*\d", re.I)  # "KEEEPTOKEN178", "keeper token 2"

CONTRACTIONS = [
    (r"\b([Cc])an['’]t\b", r"\1annot"), (r"\b([Ww])on['’]t\b", r"\1ill not"),
    (r"\b([Ss])han['’]t\b", r"\1hall not"), (r"\b(\w+)n['’]t\b", r"\1 not"),
    (r"\b([Ii])t['’]s\b", r"\1t is"), (r"\b([Tt])hat['’]s\b", r"\1hat is"),
    (r"\b([Tt])here['’]s\b", r"\1here is"), (r"\b([Hh])ere['’]s\b", r"\1ere is"),
    (r"\b([Ww])hat['’]s\b", r"\1hat is"), (r"\b([Ww])ho['’]s\b", r"\1ho is"),
    (r"\b(\w+)['’]re\b", r"\1 are"), (r"\b(\w+)['’]ve\b", r"\1 have"),
    (r"\b(\w+)['’]ll\b", r"\1 will"), (r"\b(\w+)['’]d\b", r"\1 would"),
]
FIRST_PERSON = re.compile(r"\b(I|we|We|our|Our|ours|us|you|You|your|Your|yours|let['’]s|Let['’]s)\b")


def lock(text):
    text = PH.sub(lambda m: f"${m.group(0)}$", text)
    out, last = [], 0
    for m in REF.finditer(text):
        out.append(text[last:m.start()])
        out.append(f"${m.group(0)}$")
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def unlock(text):
    return re.sub(r"\$([^$\n]+?)\$", r"\1", text)


def mechanical(text):
    """The user's allowed post-humanize edits only: dashes and contractions."""
    t = text
    t = re.sub(r"(\d)\s*[–—]\s*(\d)", r"\1 to \2", t)          # 2–6 -> 2 to 6
    t = re.sub(r"(\w)–(\w)", r"\1-\2", t)                        # cloud–edge -> cloud-edge
    t = re.sub(r"\s*—\s*", ", ", t)                              # em dash -> comma
    t = re.sub(r"\s+[–-]{1,2}\s+", ", ", t)                      # spaced dash -> comma
    t = re.sub(r",\s*([,.;:])", r"\1", t)
    for pat, rep in CONTRACTIONS:
        t = re.sub(pat, rep, t)
    return t


def first_person(entry_id, text):
    for m in FIRST_PERSON.finditer(PH.sub(" ", text)):
        print(f"FIRST PERSON id {entry_id}: ...{text[max(0, m.start() - 70):m.end() + 50]}...")


def _export_to(docx, d):
    shutil.rmtree(d, ignore_errors=True)
    subprocess.run([sys.executable, os.path.join(HERE, "style_cleanup.py"), "export", docx, d],
                   check=True, capture_output=True)


def export(docx):
    _export_to(docx, OUT)
    print(f"exported to {OUT}")


def prep(n, words=2500):
    entries = json.load(open(os.path.join(OUT, f"ch{n}.json"), encoding="utf-8"))
    chunks, cur, cur_w = [], [], 0
    for e in entries:
        if e["kind"] != "body" or "$" in e["text"]:
            continue
        w = len(PH.sub("", e["text"]).split())
        if cur and cur_w + w > words:
            chunks.append(cur)
            cur, cur_w = [], 0
        cur.append({"type": "body", "text": lock(e["text"]), "id": e["id"], "export_text": e["text"]})
        cur_w += w
    if cur:
        chunks.append(cur)
    for k, c in enumerate(chunks, 1):
        path = os.path.join(OUT, f"ch{n}.c{k}.blocks.json")
        if os.path.exists(path):
            sys.exit(f"{path} exists; refusing to overwrite (it may hold humanized text)")
        json.dump(c, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"ch{n}.c{k}: {len(c)} paragraphs, "
              f"{sum(len(PH.sub('', b['export_text']).split()) for b in c)} words")


def _chunk_files(n):
    files = sorted((f for f in os.listdir(OUT) if re.fullmatch(rf"ch{n}\.c\d+\.blocks\.json", f)),
                   key=lambda f: int(f.split(".c")[1].split(".")[0]))
    if not files and os.path.exists(os.path.join(OUT, f"ch{n}.blocks.json")):
        files = [f"ch{n}.blocks.json"]  # older single-file layout
    return [os.path.join(OUT, f) for f in files]


def patch(n):
    patches, skipped = [], []
    for f in _chunk_files(n):
        for b in json.load(open(f, encoding="utf-8")):
            if b.get("finished_text"):  # candidate with formulas put back (rh_candidates.py)
                new = b["finished_text"]
            elif not b.get("humanized"):
                skipped.append(b["id"])
                continue
            else:
                new = mechanical(unlock(b["text"]))
            # a misspelled placeholder is a lost formula: never write it to Word
            if LOST_TOKEN.search(new) or sorted(PH.findall(new)) != sorted(PH.findall(b["export_text"])):
                print(f"id {b['id']}: formula placeholder lost or misspelled -> fix by hand first")
                skipped.append(b["id"])
                continue
            first_person(b["id"], new)
            patches.append({"id": b["id"], "new": new})
    shutil.rmtree(APPLY, ignore_errors=True)
    os.makedirs(APPLY)
    shutil.copy(os.path.join(OUT, f"ch{n}.json"), APPLY)
    json.dump(patches, open(os.path.join(APPLY, f"ch{n}.patches.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"ch{n}: {len(patches)} patches, kept as they are (not humanized / skipped): {skipped}")


def mech(n, docx):
    """Dash/contraction fixes on chapter n as it is in Word now; prints first-person hits."""
    _export_to(docx, APPLY)
    for f in os.listdir(APPLY):
        if f != f"ch{n}.json":
            os.remove(os.path.join(APPLY, f))
    entries = json.load(open(os.path.join(APPLY, f"ch{n}.json"), encoding="utf-8"))
    patches = []
    for e in entries:
        if e["kind"] != "body":
            continue
        new = mechanical(e["text"])
        if new != e["text"]:
            patches.append({"id": e["id"], "new": new})
        first_person(e["id"], e["text"])
    json.dump(patches, open(os.path.join(APPLY, f"ch{n}.patches.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"ch{n}: {len(patches)} paragraph(s) with dash/contraction fixes")


def scantext(n, docx):
    d = os.path.join(HERE, "rehumanize_scan")
    _export_to(docx, d)
    entries = json.load(open(os.path.join(d, f"ch{n}.json"), encoding="utf-8"))
    paras = [PH.sub(lambda m: (e.get("math") or {}).get(m.group(0)[2:-2], ""), e["text"])
             for e in entries if e["kind"] == "body"]
    path = os.path.join(OUT, f"ch{n}.scan.txt")
    open(path, "w", encoding="utf-8").write("\n\n".join(paras))
    shutil.rmtree(d, ignore_errors=True)
    print(f"{path}: {sum(len(p.split()) for p in paras)} words")


def stats():
    tot = 0
    for n in range(1, 100):
        f = os.path.join(OUT, f"ch{n:02d}.json")
        if not os.path.exists(f):
            continue
        body = [e for e in json.load(open(f, encoding="utf-8")) if e["kind"] == "body"]
        w = sum(len(PH.sub("", e["text"]).split()) for e in body)
        tot += w
        print(f"ch{n:02d}: {len(body)} paragraphs, {w} words, ~{-(-w // 2400)} runs")
    print("total words", tot)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "export":
        export(sys.argv[2])
    elif cmd == "prep":
        prep(sys.argv[2].zfill(2), int(sys.argv[3]) if len(sys.argv) > 3 else 2500)
    elif cmd == "patch":
        patch(sys.argv[2].zfill(2))
    elif cmd == "mech":
        mech(sys.argv[2].zfill(2), sys.argv[3])
    elif cmd == "scantext":
        scantext(sys.argv[2].zfill(2), sys.argv[3])
    elif cmd == "stats":
        stats()
