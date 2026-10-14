"""
MCP server exposing the book-writing tools to Claude Code.

Claude is the orchestrator (see .claude/skills/write-book/SKILL.md). This
server only provides small, deterministic tools: talk to ChatGPT, humanize,
convert/validate blocks, write and read back the Word document, and keep a
progress ledger. It makes no workflow decisions.

All browser and Word work runs on ONE dedicated thread, because Playwright's
sync API and COM objects must stay on the thread that created them.
"""

import sys

# The MCP protocol owns stdout. The existing tools print progress, so route
# every print() to stderr and hand the real stdout to the MCP transport.
_PROTOCOL_STDOUT = sys.stdout
sys.stdout = sys.stderr

import asyncio  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from io import TextIOWrapper  # noqa: E402

import anyio  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from tools import blocks as blk  # noqa: E402
from tools import docx_writer  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config.json")
PROJECTS_DIR = os.path.join(ROOT, "projects")


def _init_worker():
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass


_worker = ThreadPoolExecutor(max_workers=1, initializer=_init_worker)
_state = {"chat_open_for": None}

mcp = FastMCP("book-agent")


async def _run(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_worker, lambda: fn(*args, **kwargs))


# ── Project helpers ───────────────────────────────────────────────────────────

def _config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _project(name: str) -> dict:
    projects = _config().get("projects", {})
    if name not in projects:
        raise ValueError(f"Project '{name}' not in config.json. Known: {sorted(projects)}")
    p = dict(projects[name])
    p.pop("outlines", None)
    p.pop("section_outlines", None)
    p["name"] = name
    p["dir"] = os.path.join(PROJECTS_DIR, name)
    os.makedirs(p["dir"], exist_ok=True)
    return p


def _path(project: dict, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(project["dir"], rel)


def _log(project: dict, msg: str):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, file=sys.stderr)
    log_dir = os.path.join(project["dir"], "logs")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "run.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _ledger_path(project: dict) -> str:
    return os.path.join(project["dir"], "ledger.json")


def _ledger(project: dict) -> dict:
    path = _ledger_path(project)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"chapters": {}, "figures": {}}


def _save_ledger(project: dict, ledger: dict):
    tmp = _ledger_path(project) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _ledger_path(project))


def _load_blocks(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_blocks(path: str, data: list[dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _ends_cleanly(text: str) -> bool:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return bool(lines) and bool(re.search(r"[.!?)\]\"'”’`$|]$|^#", lines[-1]))


# ── Auto-diagnose / auto-fix reporting (Book Dev) ─────────────────────────────
# Small fixes are recorded and sent as one AUTO-FIX REPORT per unit
# (bookdev_report); serious problems ping the owner at once. Messaging must
# never break a tool, so failures here are only logged.

def _note_fixes(where: str, fixes: list[str]):
    try:
        from tools import bookdev
        bookdev.note_fixes(where, fixes)
    except Exception as e:
        print(f"note_fixes failed: {e}", file=sys.stderr)


def _alert(title: str, lines: list[str]):
    try:
        from tools import bookdev
        bookdev.alert(title, lines)
    except Exception as e:
        print(f"alert failed: {e}", file=sys.stderr)


_CHATGPT_TROUBLE_RE = re.compile(
    r"you'?ve reached (?:the|your)|usage (?:cap|limit)|limit for (?:gpt|this model)|"
    r"something went wrong|network error|unusual activity|log in to continue|session (?:has )?expired",
    re.I)


async def _autofix_file(p: dict, path: str, where: str) -> list[str]:
    """Run the automatic block repairs on a blocks file (numbering from Word)."""
    from tools import autofix
    blocks = _load_blocks(path)
    doc = await _run(docx_writer.inspect, p["word_file_path"], 0)
    blocks, fixes = autofix.fix_blocks(blocks, doc.get("next_figure_number"),
                                       doc.get("next_table_number"))
    if fixes:
        _save_blocks(path, blocks)
        _note_fixes(where, fixes)
    return fixes


# ── Status / ledger ───────────────────────────────────────────────────────────

@mcp.tool()
async def project_status(project: str) -> dict:
    """Project settings, the progress ledger, and a summary of the Word document
    (counts of figures/tables/equations already in it and the next numbers Word
    will assign). Call this first in every session."""
    p = _project(project)
    doc = await _run(docx_writer.inspect, p["word_file_path"], 5)
    return {
        "project": project,
        "project_dir": p["dir"],
        "chat_url": p.get("chat_url"),
        "word_file_path": p["word_file_path"],
        "brief_exists": os.path.exists(os.path.join(p["dir"], "brief.md")),
        "ledger": _ledger(p),
        "document": doc,
    }


@mcp.tool()
async def ledger_update(project: str, chapter: str, fields: dict, section: str = "") -> dict:
    """Merge *fields* into the ledger entry for a chapter, or for one section
    of it when *section* is given (e.g. chapter "1", section "1.3").
    Use to record status, plan, notes, and issues needing the user."""
    p = _project(project)
    ledger = _ledger(p)
    ch = ledger["chapters"].setdefault(str(chapter), {"sections": {}})
    target = ch["sections"].setdefault(section, {}) if section else ch
    target.update(fields)
    target["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_ledger(p, ledger)
    return {"ok": True, "entry": target}


# ── ChatGPT ───────────────────────────────────────────────────────────────────

def _ensure_chat(p: dict, force: bool = False) -> str:
    """Open the book's single ChatGPT chat (config.json chat_url). One chat per
    book on purpose: ChatGPT keeps full context, so nothing gets repeated."""
    from tools.browser_tool import navigate_to_chat
    if _state["chat_open_for"] == p["name"] and not force:
        return "already open"
    result = navigate_to_chat(p["chat_url"], p.get("browser", "chrome"), progress=lambda m: _log(p, m))
    if result.lower().startswith(("warning", "error")):
        raise RuntimeError(result)
    _state["chat_open_for"] = p["name"]
    return result


_STOP_SELECTORS = 'button[data-testid="stop-button"], button[aria-label="Stop generating"], button[aria-label="Stop streaming"]'


def _wait_until_stable(p: dict, quiet_sec: int = 20, max_sec: int = 3000) -> None:
    """Long book chats get slow. Before reading a reply, wait until ChatGPT's
    stop button is gone and the reply text has not changed for *quiet_sec*."""
    from tools import browser_tool
    page = browser_tool._page
    if not page or page.is_closed():
        return
    deadline = time.time() + max_sec
    last, stable_since, last_report = None, time.time(), time.time()
    while time.time() < deadline:
        try:
            generating = page.locator(_STOP_SELECTORS).count() > 0
            text = browser_tool._extract_last_response(page)
        except Exception:
            generating, text = True, last
        if generating or text != last:
            last, stable_since = text, time.time()
        elif time.time() - stable_since >= quiet_sec:
            return
        if time.time() - last_report > 60:
            _log(p, f"still generating ({len(text or '')} chars so far)")
            last_report = time.time()
        page.wait_for_timeout(3_000)
    _log(p, "warning: reply still changing after max wait")


@mcp.tool()
async def chatgpt_open(project: str, new_chapter: bool = False) -> dict:
    """Open the book's ChatGPT chat (waits for login if needed).
    new_chapter=True also resets the per-chapter figure download cache."""
    p = _project(project)

    def work():
        from tools.browser_tool import clear_figure_src_cache
        msg = _ensure_chat(p, force=True)
        if new_chapter:
            clear_figure_src_cache()
        return msg

    return {"ok": True, "chat_url": p["chat_url"], "message": await _run(work)}


@mcp.tool()
async def chatgpt_send(project: str, save_as: str, prompt: str = "", prompt_file: str = "") -> dict:
    """Send a prompt to ChatGPT, wait for the full reply, save it as markdown.

    save_as: path relative to the project dir, e.g. "work/ch01/1.3.response.md".
    prompt_file: send a file's contents instead of *prompt* (relative to project dir).
    Returns the reply text plus `ends_cleanly` (False suggests truncation)."""
    p = _project(project)
    if prompt_file:
        with open(_path(p, prompt_file), encoding="utf-8") as f:
            prompt = f.read()
    if not prompt.strip():
        raise ValueError("Empty prompt.")

    diagnosis: list[str] = []

    def work():
        from tools.browser_tool import get_last_response, send_message
        _ensure_chat(p)
        _log(p, f"chatgpt_send -> {save_as} ({len(prompt)} chars)")
        started = time.time()
        try:
            status = send_message(prompt, progress=lambda m: _log(p, m))
            if status.lower().startswith("error"):
                raise RuntimeError(status)
        except Exception as e:
            # Usually a stale page: reopen the chat and send once more.
            diagnosis.append(f"send failed ({str(e)[:120]}) -> reopened the chat and resent")
            _ensure_chat(p, force=True)
            status = send_message(prompt, progress=lambda m: _log(p, m))
            if status.lower().startswith("error"):
                raise RuntimeError(status)
        _wait_until_stable(p)
        reply_text = get_last_response()
        if not _ends_cleanly(reply_text):
            # A long reply can pause mid-stream; give it time and read again.
            _wait_until_stable(p, quiet_sec=60)
            again = get_last_response()
            if len(again) > len(reply_text):
                diagnosis.append(f"reply looked cut off -> waited and re-read "
                                 f"({len(reply_text)} -> {len(again)} chars)")
                reply_text = again
        seconds = round(time.time() - started)
        _log(p, f"chatgpt_send <- {len(reply_text)} chars in {seconds}s")
        return status, reply_text, seconds

    try:
        status, reply, seconds = await _run(work)
    except Exception as e:
        _alert("ChatGPT send failed", [f"{save_as}: {str(e)[:200]}",
                                       "Check the ChatGPT window (login or limit?)."])
        raise
    out = _path(p, save_as)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(reply)
    trouble = _CHATGPT_TROUBLE_RE.search(reply[-600:]) if len(reply) < 3000 else None
    if trouble or not reply.strip():
        _alert("ChatGPT problem", [f"{save_as}: reply says {trouble.group(0)!r}" if trouble
                                   else f"{save_as}: empty reply", "Check the ChatGPT window."])
    _note_fixes(save_as, diagnosis)
    return {"status": status, "saved_to": out, "chars": len(reply), "seconds": seconds,
            "ends_cleanly": _ends_cleanly(reply), "diagnosis": diagnosis, "response": reply}


@mcp.tool()
async def chatgpt_read_last(project: str, save_as: str) -> dict:
    """Read the latest ChatGPT reply without sending anything (for recovery)."""
    p = _project(project)

    def work():
        from tools.browser_tool import get_last_response
        _ensure_chat(p)
        _wait_until_stable(p)
        return get_last_response()

    reply = await _run(work)
    out = _path(p, save_as)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(reply)
    return {"saved_to": out, "chars": len(reply), "ends_cleanly": _ends_cleanly(reply), "response": reply}


@mcp.tool()
async def chatgpt_rules(project: str, topic: str = "all", send: bool = False, save_as: str = "") -> dict:
    """The user's formatting rules (the Discord /instruct presets) and the exact
    chapter prompts used by /writecompletechapter, read live from agent_core.py.
    These are the single source of truth: never paraphrase them.

    topic: all | headings | prose | equations | length | figures | tables |
           norepeat | summary | conclude
    send=True sends the rule text to ChatGPT verbatim (save_as required)."""
    import agent_core as ac
    if topic not in ac.FORMATTING_INSTRUCTIONS:
        raise ValueError(f"Unknown topic. Choose from {sorted(ac.FORMATTING_INSTRUCTIONS)}")
    text = ac.FORMATTING_INSTRUCTIONS[topic]
    prompts = {
        "outline": ac.OUTLINE_PROMPT_TEMPLATE,
        "intro": ac.INTRO_PROMPT_TEMPLATE,
        "continue": ac.CONTINUE_PROMPT,
        "complete_truncated": ac.COMPLETE_TRUNCATED_PROMPT,
        "conclude": ac.CONCLUDE_CHAPTER_PROMPT,
        "draw_figure": "Draw figure {n} please!",
    }
    result = {"topic": topic, "rules": text, "prompts": prompts}
    if send:
        if not save_as:
            raise ValueError("save_as is required when send=True.")
        result["reply"] = await chatgpt_send(project, save_as=save_as, prompt=text)
    return result


@mcp.tool()
async def chatgpt_draw_figure(project: str, number: int, prompt: str = "", gpt_number: int = 0) -> dict:
    """Ask ChatGPT to draw figure *number* and download the image.

    number: the figure's number in the book (= Word's caption number; names the file).
    gpt_number: the number ChatGPT used for it, if different (the block's "gpt_number").
    prompt defaults to "Draw figure <gpt_number or number> please!". For a redraw, pass a specific
    prompt describing exactly what to fix. Each attempt is saved as a new file.
    Returns the image path, size, and `duplicate_of` if identical to an earlier figure.
    View the image with the Read tool before accepting it."""
    p = _project(project)
    fig_dir = os.path.join(p["dir"], "figures")
    os.makedirs(fig_dir, exist_ok=True)
    attempt = 1
    while os.path.exists(os.path.join(fig_dir, f"fig_{number:03d}_v{attempt}.png")):
        attempt += 1
    save_path = os.path.join(fig_dir, f"fig_{number:03d}_v{attempt}.png")
    text = prompt.strip() or f"Draw figure {gpt_number or number} please!"

    def work():
        from tools.browser_tool import (download_last_generated_image, get_message_count,
                                        send_message, snapshot_existing_figure_srcs)
        _ensure_chat(p)
        baseline = get_message_count()
        snapshot_existing_figure_srcs()
        _log(p, f"figure {number}: requesting (attempt {attempt})")
        send_message(text, allow_retry=False, progress=lambda m: _log(p, m))
        return download_last_generated_image(save_path, progress=lambda m: _log(p, m),
                                             baseline_msg_count=baseline)

    diagnosis = []
    try:
        ok = await _run(work)
    except Exception as e:
        ok = False
        diagnosis.append(f"draw failed ({str(e)[:120]})")
    if not ok or not os.path.exists(save_path):
        # The image is often in the chat but missed by the scan: look for a new one
        # (content not matching any figure file saved so far) before asking again.
        def recover():
            import hashlib
            from tools.browser_tool import _finalize_image, fetch_recent_chat_images
            known = set()
            for f in os.listdir(fig_dir):
                with open(os.path.join(fig_dir, f), "rb") as fh:
                    known.add(hashlib.sha1(fh.read()).hexdigest())
            for data in fetch_recent_chat_images():
                if hashlib.sha1(data).hexdigest() not in known:
                    with open(save_path, "wb") as fh:
                        fh.write(data)
                    return bool(_finalize_image(save_path))  # normalize to PNG
            return False
        try:
            if await _run(recover):
                ok = True
                diagnosis.append(f"figure {number}: image was in the chat but the download missed it "
                                 "-> recovered it from the chat (no new request)")
        except Exception as e:
            diagnosis.append(f"figure {number}: chat image recovery failed ({str(e)[:100]})")
    if not ok or not os.path.exists(save_path):
        # Not in the chat at all: reopen the chat and ask again once.
        diagnosis.append(f"figure {number}: no new image in the chat -> reopened the chat and asked again")
        text = f"Please draw figure {gpt_number or number} again as an image."

        def reopen():
            _ensure_chat(p, force=True)
        try:
            await _run(reopen)
            ok = await _run(work)
        except Exception as e:
            ok = False
            diagnosis.append(f"retry failed ({str(e)[:120]})")
    if not ok or not os.path.exists(save_path):
        _alert(f"Figure {number} could not be downloaded",
               diagnosis + ["Check the ChatGPT window (image limit or login?)."])
        return {"ok": False, "number": number, "diagnosis": diagnosis,
                "message": "Image could not be downloaded after an automatic retry. "
                "Check the ChatGPT window."}
    info = blk.image_info(save_path)
    dup = None
    for n, f in _ledger(p).get("figures", {}).items():
        if f.get("sha1") == info.get("sha1") and int(n) != number:
            dup = int(n)
    if dup:
        diagnosis.append(f"figure {number}: image is identical to figure {dup}; redraw it")
    _note_fixes(f"figure {number}", diagnosis)
    return {"ok": True, "number": number, "image": save_path, **info, "duplicate_of": dup,
            "diagnosis": diagnosis}


# ── Blocks ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def markdown_to_blocks(project: str, markdown_file: str, out_file: str) -> dict:
    """Convert a saved ChatGPT markdown reply into a blocks JSON file, then validate.
    Read and edit the JSON file directly to fix anything."""
    p = _project(project)
    with open(_path(p, markdown_file), encoding="utf-8") as f:
        md = f.read()
    blocks = blk.markdown_to_blocks(md)
    out = _path(p, out_file)
    _save_blocks(out, blocks)
    fixes = await _autofix_file(p, out, out_file)
    blocks = _load_blocks(out)
    return {"saved_to": out, "blocks": len(blocks), "autofix": fixes,
            "validation": blk.validate_blocks(blocks)}


@mcp.tool()
async def autofix_blocks(project: str, blocks_file: str) -> dict:
    """Auto-diagnose and repair a blocks file: broken LaTeX escapes / control
    characters, equation labels and \\tag{}, LaTeX that won't convert to Word math,
    ChatGPT wrappers/chatter/"Placement:" leftovers, curly quotes, stray spaces,
    and figure/table numbers that don't continue from Word's (renumbered, with the
    prose references remapped). Each fix is listed and queued for the user's
    AUTO-FIX report. Run after edits; docx_append also runs it before writing."""
    p = _project(project)
    path = _path(p, blocks_file)
    fixes = await _autofix_file(p, path, blocks_file)
    return {"autofix": fixes, "validation": blk.validate_blocks(_load_blocks(path))}


@mcp.tool()
async def validate_blocks(project: str, blocks_file: str) -> dict:
    """Validate a blocks file: equations convert to Word math (unnumbered, no
    numbered references), tables are rectangular with captions, figures have
    images, figure/table numbers continue exactly from Word's caption count, no
    leftover markdown, placeholders or ChatGPT chatter, plus grammar-smell
    warnings. Errors must be fixed before docx_append will write."""
    p = _project(project)
    blocks = _load_blocks(_path(p, blocks_file))
    report = blk.validate_blocks(blocks)
    doc = await _run(docx_writer.inspect, p["word_file_path"], 0)
    report["errors"] += blk.check_numbering(blocks, doc.get("next_figure_number", 1),
                                            doc.get("next_table_number", 1))
    report["word_next_figure"] = doc.get("next_figure_number", 1)
    report["word_next_table"] = doc.get("next_table_number", 1)
    return report


_KEEP_RE = re.compile(r"keep\s*token\s*(\d+)", re.I)


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@mcp.tool()
async def humanize_blocks(project: str, blocks_file: str, max_tokens_per_paragraph: int = 6,
                          sentence_mode: bool = False, max_words_per_run: int = 4900,
                          auto: bool = True) -> dict:
    """Humanize body paragraphs through StealthWriter, in as few runs as the
    plan's word limit allows (max_words_per_run, default 4,900; plan limit 5,000).

    Inline math and bold/italic spans are swapped for KEEPTOKEN placeholders
    first and restored afterwards, so equations are never altered. Paragraphs
    with more than *max_tokens_per_paragraph* spans (or every one when
    sentence_mode=True) are humanized around the math instead: runs of sentences
    without math are sent as chunks, sentences containing math stay as they are.
    Blocks with "humanize": false, or already humanized, are skipped. The
    original text is kept in each block's "original" field for review.

    auto=True (default) diagnoses and fixes small failures itself, and lists
    what it did in `diagnosis`:
    - every run starts on a freshly reloaded humanizer page (no stale result);
    - a run that errors or times out, or comes back with the wrong paragraph
      count, is retried once;
    - a paragraph whose placeholders were lost is re-sent in sentence mode, and a
      paragraph sentence mode could not handle is re-sent whole;
    - a paragraph in which every sentence contains math is left as written
      (math is never humanized), marked "humanize": false and listed in
      math_only_blocks;
    - quota exhausted: stops at once and `problems` starts with "QUOTA".
    Whatever still fails is listed in not_humanized_blocks / problems."""
    p = _project(project)
    path = _path(p, blocks_file)
    blocks = _load_blocks(path)

    modes: dict[int, str] = {}
    for i, b in enumerate(blocks):
        if b["type"] != "body" or b.get("humanized") or b.get("humanize") is False:
            continue
        n_spans = len(blk.INLINE_RE.findall(b["text"]))
        modes[i] = "sentences" if sentence_mode or n_spans > max_tokens_per_paragraph else "whole"
    if not modes:
        return {"humanized": 0, "message": "No eligible body paragraphs."}

    tried: dict[int, set] = {i: set() for i in modes}
    diagnosis, problems, math_only = [], [], []
    done, runs, all_spans = 0, 0, {}
    for _pass in range(2 if auto else 1):
        todo = {i: m for i, m in modes.items()
                if not blocks[i].get("humanized") and m not in tried[i]}
        if not todo:
            break
        res = await _humanize_pass(p, path, blocks, todo, max_words_per_run, auto,
                                   diagnosis, problems)
        done += res["done"]
        runs += res["runs"]
        all_spans.update(res["spans"])
        for i, m in todo.items():
            tried[i].add(m)
        if res["quota"] or not auto:
            break
        for i, m in todo.items():
            if blocks[i].get("humanized"):
                continue
            other = "sentences" if m == "whole" else "whole"
            if other not in tried[i]:
                why = ("placeholders lost or run failed" if m == "whole"
                       else "no math-free sentence to send or run failed")
                diagnosis.append(f"block {i}: {m} mode failed ({why}) -> retrying in {other} mode")
                modes[i] = other

    if auto and not any(pr.startswith("QUOTA") for pr in problems):
        for i in modes:
            b = blocks[i]
            if b.get("humanized"):
                continue
            text = blk.INLINE_RE.sub("KEEPTOKEN", b["text"])
            if all("KEEPTOKEN" in s for s in _SENTENCE_SPLIT_RE.split(text)):
                b["humanize"] = False
                b["humanize_note"] = "every sentence contains math; kept as written"
                math_only.append(i)
        if math_only:
            diagnosis.append(f"blocks {math_only}: every sentence contains math -> kept as written")
            _save_blocks(path, blocks)

    not_humanized = [i for i, b in enumerate(blocks) if b["type"] == "body"
                     and not b.get("humanized") and b.get("humanize") is not False]
    _note_fixes(f"{blocks_file} humanize", diagnosis)
    if any(pr.startswith("QUOTA") for pr in problems):
        _alert("StealthWriter quota used up", [f"{blocks_file}: humanizing stopped.",
                                               "Work waits until the quota resets or you log in again."])
    elif not_humanized:
        _alert("Paragraphs still not humanized", [f"{blocks_file}: blocks {not_humanized}"]
               + problems[:3])
    return {"humanized": done, "runs": runs, "problems": problems, "diagnosis": diagnosis,
            "math_only_blocks": math_only,
            "kept_original_blocks": [i for i in modes if i in not_humanized],
            "not_humanized_blocks": not_humanized,
            "spans": all_spans if problems else {},
            "validation": blk.validate_blocks(blocks)}


async def _humanize_pass(p, path, blocks, modes, max_words_per_run, auto, diagnosis, problems):
    """One humanize pass over the blocks in *modes* ({index: "whole"|"sentences"})."""
    # plans[i] = list of segments [protected_text, target_index_or_None]
    plans: dict[int, list] = {}
    locals_: dict[int, dict] = {}
    protected, spans = [], []
    for i, mode in modes.items():
        local: dict[int, str] = {}

        def repl(m):
            idx = len(spans)
            spans.append(m.group(0))
            local[idx] = m.group(0)
            return f"KEEPTOKEN{idx}"

        text = blk.INLINE_RE.sub(repl, blocks[i]["text"])
        locals_[i] = local
        if mode == "whole":
            plans[i] = [[text, len(protected)]]
            protected.append(text)
            continue
        segs, run = [], []
        for s in _SENTENCE_SPLIT_RE.split(text):
            if "KEEPTOKEN" in s:
                if run:
                    segs.append([" ".join(run), len(protected)])
                    protected.append(" ".join(run))
                    run = []
                segs.append([s, None])
            else:
                run.append(s)
        if run:
            segs.append([" ".join(run), len(protected)])
            protected.append(" ".join(run))
        if any(t is not None for _, t in segs):
            plans[i] = segs

    result = {"done": 0, "runs": 0, "quota": False,
              "spans": {f"KEEPTOKEN{i}": s for i, s in enumerate(spans)}}
    if not protected:
        return result

    # StealthWriter's plan limit is 5,000 words per run: send batches well under it.
    batches, cur, cur_words = [], [], 0
    for idx, text in enumerate(protected):
        words = len(text.split())
        if cur and cur_words + words > max_words_per_run:
            batches.append(cur)
            cur, cur_words = [], 0
        cur.append(idx)
        cur_words += words
    if cur:
        batches.append(cur)
    result["runs"] = len(batches)

    paras: list = [None] * len(protected)
    for n, batch in enumerate(batches, 1):
        joined = "\n\n".join(protected[k] for k in batch)

        def work(joined=joined, n=n, batch=batch):
            from tools.stealthwriter_tool import humanize_text
            _log(p, f"humanize run {n}/{len(batches)}: {len(batch)} paragraph(s), "
                    f"{len(joined.split())} words")
            return humanize_text(joined, browser_name=p.get("browser", "chrome"),
                                 progress=lambda m: _log(p, m))

        attempts = 2 if auto else 1
        for a in range(attempts):
            last = a + 1 == attempts
            try:
                out_text = await _run(work)
            except Exception as e:
                msg = str(e)
                if "QUOTA" in msg:
                    problems.append(f"QUOTA: {msg}")
                    result["quota"] = True
                    break
                if not last:
                    diagnosis.append(f"run {n}: {type(e).__name__}: {msg[:150]} -> reloading and retrying")
                    continue
                problems.append(f"run {n}: {type(e).__name__}: {msg[:200]}")
                break
            if out_text.strip() == joined.strip():
                problems.append(f"run {n}: StealthWriter returned the original text "
                                "(human score below threshold after 'Humanize More')")
                break
            out = [x.strip() for x in re.split(r"\n\s*\n", out_text.strip()) if x.strip()]
            if len(out) != len(batch):
                raw = path.replace(".json", "") + f".humanized_raw_run{n}.txt"
                with open(raw, "w", encoding="utf-8") as f:
                    f.write(out_text)
                if not last:
                    diagnosis.append(f"run {n}: paragraph count mismatch (sent {len(batch)}, "
                                     f"got {len(out)}) -> reloading and retrying")
                    continue
                problems.append(f"run {n}: paragraph count mismatch (sent {len(batch)}, got "
                                f"{len(out)}); raw output saved to {raw}")
                break
            for k, para in zip(batch, out):
                paras[k] = para
            break
        if result["quota"]:
            break

    restore = lambda s: _KEEP_RE.sub(lambda m: spans[int(m.group(1))], s)
    for i, segs in plans.items():
        if any(t is not None and paras[t] is None for _, t in segs):
            continue
        whole = len(segs) == 1 and segs[0][1] is not None
        if whole:
            para = paras[segs[0][1]]
            found = [int(n) for n in _KEEP_RE.findall(para)]
            if sorted(found) != sorted(locals_[i]):
                continue
            new_text = restore(para)
        else:
            # chunks carry no placeholders; math sentences are restored as-is
            new_text = " ".join(restore(paras[t]) if t is not None else restore(s) for s, t in segs)
        blocks[i]["original"] = blocks[i]["text"]
        blocks[i]["text"] = new_text
        blocks[i]["humanized"] = True
        result["done"] += 1

    _save_blocks(path, blocks)
    return result


# ── Book Dev (Discord now, WhatsApp later) ────────────────────────────────────

@mcp.tool()
async def bookdev_send(message: str) -> dict:
    """Book Dev: reply to the owner on Discord (default) or WhatsApp
    (BOOKDEV_CHANNEL=whatsapp in .env). Long text is split into several
    messages. Use it to answer the owner's Book Dev messages and for stop
    conditions (quota, login, locked Word file)."""
    from tools import bookdev
    return await _run(bookdev.send, message)


@mcp.tool()
async def bookdev_report(title: str) -> dict:
    """Book Dev: send all automatic fixes recorded since the last report as one
    "🛠️ AUTO-FIX REPORT" message (call after each unit is written to Word).
    Sends nothing when there were no fixes. Serious problems are pinged at once
    by the tools themselves."""
    from tools import bookdev
    return await _run(bookdev.report_fixes, title)


@mcp.tool()
async def bookdev_inbox(mark_read: bool = True) -> dict:
    """Book Dev: the owner's messages not yet read, oldest first. The listener
    must be running (python bookdev_discord.py, or the WhatsApp webhook)."""
    from tools import bookdev
    msgs = bookdev.inbox(mark_read)
    return {"messages": msgs, "count": len(msgs), "channel": bookdev.channel()}


@mcp.tool()
async def stealthwriter_open(project: str) -> dict:
    """Open StealthWriter so the user can log in (after logout / quota reset)."""
    p = _project(project)

    def work():
        from tools.stealthwriter_tool import open_stealthwriter_for_login
        return open_stealthwriter_for_login(p.get("browser", "chrome"), progress=lambda m: _log(p, m))

    return {"message": await _run(work)}


# ── Word ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def docx_append(project: str, blocks_file: str, chapter: str, section: str,
                      force: bool = False) -> dict:
    """Validate, back up the Word file, append the blocks, and mark the section
    as written in the ledger. Refuses if validation has errors, or if the
    section is already written (pass force=True only to deliberately re-append)."""
    p = _project(project)
    ledger = _ledger(p)
    sec = ledger["chapters"].get(str(chapter), {}).get("sections", {}).get(section, {})
    if sec.get("status") == "written" and not force:
        return {"ok": False, "message": f"Section {section} is already written "
                f"({sec.get('written_at')}). Use force=True to append again."}

    fixes = await _autofix_file(p, _path(p, blocks_file), f"{chapter}/{section}")
    blocks = _load_blocks(_path(p, blocks_file))
    report = blk.validate_blocks(blocks)
    if report["errors"]:
        return {"ok": False, "message": "Validation errors. Nothing written.", "autofix": fixes, **report}

    word = p["word_file_path"]
    before = await _run(docx_writer.inspect, word, 0)
    numbering = blk.check_numbering(blocks, before.get("next_figure_number", 1),
                                    before.get("next_table_number", 1))
    if numbering:
        return {"ok": False, "message": "Caption numbers don't match Word. Nothing written.",
                "errors": numbering}

    def work():
        bk = docx_writer.backup(word, os.path.join(p["dir"], "backups"))
        # Word may hold the file briefly (or the user has it open): wait and retry.
        for attempt in range(4):
            try:
                return bk, docx_writer.append_blocks(blocks, word)
            except PermissionError:
                if attempt == 3:
                    raise RuntimeError(f"'{word}' is open in Word or locked. Ask the user to close it, then retry.")
                _log(p, f"Word file locked; retrying in 20 s ({attempt + 1}/3)")
                time.sleep(20)

    try:
        bk, msg = await _run(work)
    except RuntimeError as e:
        _alert("Word file is locked", [f"Could not write {chapter}/{section} after 1 minute of retries.",
                                       "Close the book in Word so writing can continue."])
        raise
    figs = [b for b in blocks if b["type"] == "figure"]
    for f in figs:
        info = blk.image_info(f["image"])
        ledger["figures"][str(f["number"])] = {"image": f["image"], "sha1": info.get("sha1"),
                                               "chapter": str(chapter), "section": section,
                                               "caption": f.get("caption", "")}
    ch = ledger["chapters"].setdefault(str(chapter), {"sections": {}})
    ch["sections"].setdefault(section, {}).update({
        "status": "written",
        "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "blocks_file": _path(p, blocks_file),
        "backup_before": bk,
        "figures": [f["number"] for f in figs],
        "stats": report["stats"],
    })
    _save_ledger(p, ledger)
    _log(p, f"docx_append {chapter}/{section}: {msg}")
    after = await _run(docx_writer.inspect, word, 12)
    n_tables = sum(1 for b in blocks if b["type"] == "table")
    mismatch = []
    if after.get("figure_captions") != before.get("figure_captions", 0) + len(figs):
        mismatch.append(f"Word now has {after.get('figure_captions')} figure captions, expected "
                        f"{before.get('figure_captions', 0) + len(figs)}")
    if after.get("table_captions") != before.get("table_captions", 0) + n_tables:
        mismatch.append(f"Word now has {after.get('table_captions')} table captions, expected "
                        f"{before.get('table_captions', 0) + n_tables}")
    if mismatch:
        _alert("Word check failed after writing", [f"{chapter}/{section}"] + mismatch
               + [f"Backup before this write: {bk}"])
    return {"ok": not mismatch, "message": msg, "backup": bk, "warnings": report["warnings"],
            "autofix": fixes, "post_write_mismatch": mismatch, "document": after}


@mcp.tool()
async def docx_inspect(project: str, tail: int = 25) -> dict:
    """Read back the Word document: counts of figures, tables, equations, all
    headings, and the last *tail* paragraphs. Use to verify after writing."""
    p = _project(project)
    return await _run(docx_writer.inspect, p["word_file_path"], tail)


@mcp.tool()
async def docx_health(project: str) -> dict:
    """Auto-diagnose the whole Word file (run at each chapter end): caption
    numbering, Figure/Table references past the last caption, numbered equation
    references, leftover LaTeX/markdown/ChatGPT text, duplicate headings.
    Auto-fixes chapters that don't start on a new page (backup first).
    Problems are pinged to the user on Book Dev."""
    from tools import doc_health
    p = _project(project)
    word = p["word_file_path"]
    await _run(docx_writer.backup, word, os.path.join(p["dir"], "backups"))
    res = await _run(doc_health.check, word, True)
    _note_fixes("Word file", res["fixes"])
    if res["problems"]:
        _alert("Word file check found problems", res["problems"][:10])
    return res


@mcp.tool()
async def docx_restore(project: str, backup_file: str) -> dict:
    """Restore the Word document from a backup made by docx_append (undo).
    The current file is itself backed up first."""
    import shutil
    p = _project(project)
    src = _path(p, backup_file)
    if not os.path.exists(src):
        files = sorted(os.listdir(os.path.join(p["dir"], "backups")))
        return {"ok": False, "message": "Backup not found.", "available": files[-10:]}
    word = p["word_file_path"]
    safety = docx_writer.backup(word, os.path.join(p["dir"], "backups"))
    shutil.copy2(src, word)
    return {"ok": True, "restored_from": src, "previous_saved_as": safety}


# ── Entry point ───────────────────────────────────────────────────────────────

async def _main():
    out = anyio.wrap_file(TextIOWrapper(_PROTOCOL_STDOUT.buffer, encoding="utf-8"))
    async with stdio_server(stdout=out) as (read_stream, write_stream):
        await mcp._mcp_server.run(read_stream, write_stream,
                                  mcp._mcp_server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(_main)
