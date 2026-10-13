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

    def work():
        from tools.browser_tool import get_last_response, send_message
        _ensure_chat(p)
        _log(p, f"chatgpt_send -> {save_as} ({len(prompt)} chars)")
        started = time.time()
        status = send_message(prompt, progress=lambda m: _log(p, m))
        if status.lower().startswith("error"):
            raise RuntimeError(status)
        _wait_until_stable(p)
        reply_text = get_last_response()
        seconds = round(time.time() - started)
        _log(p, f"chatgpt_send <- {len(reply_text)} chars in {seconds}s")
        return status, reply_text, seconds

    status, reply, seconds = await _run(work)
    out = _path(p, save_as)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(reply)
    return {"status": status, "saved_to": out, "chars": len(reply), "seconds": seconds,
            "ends_cleanly": _ends_cleanly(reply), "response": reply}


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

    ok = await _run(work)
    if not ok or not os.path.exists(save_path):
        return {"ok": False, "number": number, "message": "Image could not be downloaded. "
                "Retry, or check the ChatGPT window."}
    info = blk.image_info(save_path)
    dup = None
    for n, f in _ledger(p).get("figures", {}).items():
        if f.get("sha1") == info.get("sha1") and int(n) != number:
            dup = int(n)
    return {"ok": True, "number": number, "image": save_path, **info, "duplicate_of": dup}


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
    return {"saved_to": out, "blocks": len(blocks), "validation": blk.validate_blocks(blocks)}


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


@mcp.tool()
async def humanize_blocks(project: str, blocks_file: str, max_tokens_per_paragraph: int = 6) -> dict:
    """Humanize body paragraphs through StealthWriter in ONE pass.

    Inline math and bold/italic spans are swapped for KEEPTOKEN placeholders
    first and restored afterwards, so equations are never altered. A paragraph
    whose placeholders do not survive keeps its original text. Blocks with
    "humanize": false, or already humanized, are skipped. The original text
    is kept in each block's "original" field for review.
    If paragraph counts don't line up, nothing is changed and the raw output is
    saved for you to map manually."""
    p = _project(project)
    path = _path(p, blocks_file)
    blocks = _load_blocks(path)

    targets, protected, spans = [], [], []
    for i, b in enumerate(blocks):
        if b["type"] != "body" or b.get("humanized") or b.get("humanize") is False:
            continue
        local: dict[int, str] = {}

        def repl(m):
            idx = len(spans)
            spans.append(m.group(0))
            local[idx] = m.group(0)
            return f"KEEPTOKEN{idx}"

        text = blk.INLINE_RE.sub(repl, b["text"])
        if len(local) > max_tokens_per_paragraph:
            continue
        targets.append((i, local))
        protected.append(text)

    if not targets:
        return {"humanized": 0, "message": "No eligible body paragraphs."}

    joined = "\n\n".join(protected)

    def work():
        from tools.stealthwriter_tool import humanize_text
        _log(p, f"humanize: {len(targets)} paragraph(s), {len(joined)} chars")
        return humanize_text(joined, browser_name=p.get("browser", "chrome"),
                             progress=lambda m: _log(p, m))

    result = await _run(work)
    if result.strip() == joined.strip():
        return {"humanized": 0, "message": "StealthWriter returned the original text "
                "(score below threshold, quota, or login problem). Blocks unchanged."}

    paras = [x.strip() for x in re.split(r"\n\s*\n", result.strip()) if x.strip()]
    if len(paras) != len(targets):
        raw = path.replace(".json", "") + ".humanized_raw.txt"
        with open(raw, "w", encoding="utf-8") as f:
            f.write(result)
        return {"humanized": 0, "message": f"Paragraph count mismatch: sent {len(targets)}, got "
                f"{len(paras)}. Raw output saved to {raw}. KEEPTOKENn maps to spans below.",
                "raw_file": raw, "spans": {f"KEEPTOKEN{i}": s for i, s in enumerate(spans)}}

    done, kept_original = 0, []
    for (i, local), para in zip(targets, paras):
        found = [int(n) for n in _KEEP_RE.findall(para)]
        if sorted(found) != sorted(local):
            kept_original.append(i)
            continue
        restored = _KEEP_RE.sub(lambda m: spans[int(m.group(1))], para)
        blocks[i]["original"] = blocks[i]["text"]
        blocks[i]["text"] = restored
        blocks[i]["humanized"] = True
        done += 1

    _save_blocks(path, blocks)
    return {"humanized": done, "kept_original_blocks": kept_original,
            "validation": blk.validate_blocks(blocks)}


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
    blocks = _load_blocks(_path(p, blocks_file))
    report = blk.validate_blocks(blocks)
    if report["errors"]:
        return {"ok": False, "message": "Validation errors. Nothing written.", **report}

    ledger = _ledger(p)
    sec = ledger["chapters"].get(str(chapter), {}).get("sections", {}).get(section, {})
    if sec.get("status") == "written" and not force:
        return {"ok": False, "message": f"Section {section} is already written "
                f"({sec.get('written_at')}). Use force=True to append again."}

    word = p["word_file_path"]
    before = await _run(docx_writer.inspect, word, 0)
    numbering = blk.check_numbering(blocks, before.get("next_figure_number", 1),
                                    before.get("next_table_number", 1))
    if numbering:
        return {"ok": False, "message": "Caption numbers don't match Word. Nothing written.",
                "errors": numbering}

    def work():
        bk = docx_writer.backup(word, os.path.join(p["dir"], "backups"))
        try:
            msg = docx_writer.append_blocks(blocks, word)
        except PermissionError:
            raise RuntimeError(f"'{word}' is open in Word or locked. Ask the user to close it, then retry.")
        return bk, msg

    bk, msg = await _run(work)
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
    return {"ok": not mismatch, "message": msg, "backup": bk, "warnings": report["warnings"],
            "post_write_mismatch": mismatch, "document": after}


@mcp.tool()
async def docx_inspect(project: str, tail: int = 25) -> dict:
    """Read back the Word document: counts of figures, tables, equations, all
    headings, and the last *tail* paragraphs. Use to verify after writing."""
    p = _project(project)
    return await _run(docx_writer.inspect, p["word_file_path"], tail)


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
