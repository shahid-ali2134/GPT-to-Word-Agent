"""
Shared workflow helpers for the ChatGPT to Word agent.
"""

import json
import os
import re

from tools.browser_tool import get_last_response, navigate_to_chat, send_message
from tools.parser import Block, parse_inline, parse_markdown
from tools.stealthwriter_tool import humanize_text
from tools.word_tool import append_blocks_to_word

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULT_PROJECT = "book"
DEFAULT_CHAPTER_NUMBER = 1
OUTLINE_PROMPT_TEMPLATE = (
    'lets start with chapter {chapter_number} "{chapter_outline}" '
    "please provide me its outline!"
)
INTRO_PROMPT_TEMPLATE = (
    "lets start writing write the introductory paragraphs of chapter "
    "{chapter_number} before {first_section}"
)
CONTINUE_PROMPT = "continue to the next section!"
MAX_CHAPTER_STEPS = 40
SECTION_DONE_MARKER = "[SECTION_WORKFLOW_COMPLETE]"
SECTION_PROMPT_TEMPLATE = """Write only the requested part of chapter {chapter_number}.

Use this section outline exactly as the scope:
{sections_outline}

Write the complete prose for every listed section and subsection in this outline.
Do not write content outside this outline.
Do not write the chapter introduction unless it is included in this outline.
Do not write the chapter summary unless it is included in this outline.
If the content is too long, write as much as you can and stop at a clean boundary.
When all requested sections and subsections are fully complete, end your final response with:
{done_marker}"""
CONTINUE_SECTION_PROMPT = (
    "Continue writing the next remaining section or subsection from the provided "
    f"outline. When all requested material is complete, end with {SECTION_DONE_MARKER}"
)
MAX_SECTION_STEPS = 20
CHAPTER_TITLE_RE = re.compile(r"^\s*chapter\s+\d+\.?\s*[:\-]?\s*(.*?)\s*$", re.I)


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _first_section(chapter_number: str, chapter_outline: str) -> str:
    marker = f"{chapter_number}.1"
    return marker if marker in chapter_outline else f"{chapter_number}.1"


def _contains_chapter_summary(content: str) -> bool:
    lower = content.lower()
    summary_markers = (
        "chapter summary",
        "## chapter summary",
        "# chapter summary",
        f"{chr(10)}chapter summary",
    )
    return any(marker in lower for marker in summary_markers)


def _strip_done_marker(content: str) -> str:
    return content.replace(SECTION_DONE_MARKER, "").strip()


def _chapter_title_from_outline(chapter_number: int | str, chapter_outline: str) -> str:
    for line in chapter_outline.splitlines():
        line = line.strip()
        if not line:
            continue

        match = CHAPTER_TITLE_RE.match(line)
        if match:
            title = match.group(1).strip()
            return title or f"Chapter {chapter_number}"
        return line

    return f"Chapter {chapter_number}"


def _prepend_chapter_heading(blocks: list[Block], chapter_title: str) -> list[Block]:
    if not chapter_title:
        return blocks
    if blocks and blocks[0].block_type == "chapter":
        return blocks
    return [Block("chapter", parse_inline(chapter_title))] + blocks


def _split_humanized_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", text.strip()) if p.strip()]
    if paragraphs:
        return paragraphs
    return [text.strip()] if text.strip() else []


def _apply_humanized_paragraphs(
    original_blocks: list[Block],
    body_indexes: list[int],
    humanized_text: str,
) -> list[Block]:
    blocks_for_word = list(original_blocks)
    paragraphs = _split_humanized_paragraphs(humanized_text)
    if not paragraphs:
        return blocks_for_word

    for offset, block_index in enumerate(body_indexes):
        if offset >= len(paragraphs):
            break

        paragraph = paragraphs[offset]
        if offset == len(body_indexes) - 1 and len(paragraphs) > len(body_indexes):
            paragraph = "\n\n".join([paragraph] + paragraphs[len(body_indexes):])
        blocks_for_word[block_index] = Block("body", parse_inline(paragraph))

    return blocks_for_word


def _humanize_for_word(text: str, project: dict, progress=None) -> list[Block]:
    if not text or not text.strip():
        return []

    original_blocks = parse_markdown(text)
    if not original_blocks:
        return []

    body_indexes = [
        index for index, block in enumerate(original_blocks)
        if block.block_type == "body" and block.plain_text.strip()
    ]
    if not body_indexes:
        return original_blocks

    body_text = "\n\n".join(original_blocks[index].plain_text.strip() for index in body_indexes)
    if progress:
        progress(f"Humanizing {len(body_indexes)} body paragraph(s) in one StealthWriter pass.")

    humanized_text = humanize_text(
        text=body_text,
        browser_name=project.get("browser", "chrome"),
        progress=None,
    )
    return _apply_humanized_paragraphs(original_blocks, body_indexes, humanized_text)


def get_project(project_name: str = DEFAULT_PROJECT) -> dict:
    cfg = load_config()
    projects = cfg.get("projects", {})
    if project_name not in projects:
        raise ValueError(f"Project '{project_name}' is not configured in config.json.")

    project = projects[project_name].copy()
    if not project.get("chat_url"):
        raise ValueError(f"Project '{project_name}' is missing chat_url.")
    if not project.get("word_file_path"):
        raise ValueError(f"Project '{project_name}' is missing word_file_path.")

    project["name"] = project_name
    return project


def build_outline_prompt(chapter_number: int | str, chapter_outline: str) -> str:
    return OUTLINE_PROMPT_TEMPLATE.format(
        chapter_number=chapter_number,
        chapter_outline=chapter_outline,
    )


def build_intro_prompt(chapter_number: int | str, chapter_outline: str) -> str:
    chapter_number = str(chapter_number)
    return INTRO_PROMPT_TEMPLATE.format(
        chapter_number=chapter_number,
        first_section=_first_section(chapter_number, chapter_outline),
    )


def build_section_prompt(chapter_number: int | str, sections_outline: str) -> str:
    return SECTION_PROMPT_TEMPLATE.format(
        chapter_number=chapter_number,
        sections_outline=sections_outline,
        done_marker=SECTION_DONE_MARKER,
    )


def write_complete_chapter(
    project_name: str = DEFAULT_PROJECT,
    chapter_number: int = DEFAULT_CHAPTER_NUMBER,
    chapter_outline: str | None = None,
    progress=None,
) -> dict:
    """
    Run the full ChatGPT to Word chapter workflow.

    The outline response is intentionally not written to Word. Every response
    after the introductory paragraph prompt is appended until ChatGPT writes a
    Chapter Summary section.
    """
    if not chapter_outline or not chapter_outline.strip():
        raise ValueError("Chapter outline is required.")

    chapter_outline = chapter_outline.strip()
    project = get_project(project_name)
    selected_chapter = f"chapter_{chapter_number}"
    word_file_path = project["word_file_path"]
    chapter_title = _chapter_title_from_outline(chapter_number, chapter_outline)

    def report(message: str):
        if progress:
            progress(message)

    report(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(project["chat_url"], project.get("browser", "chrome"))
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    outline_prompt = build_outline_prompt(chapter_number, chapter_outline)
    report("Requesting the chapter outline from ChatGPT.")
    send_message(outline_prompt)
    outline_response = get_last_response()

    intro_prompt = build_intro_prompt(chapter_number, chapter_outline)
    report("Writing the introductory paragraphs.")
    send_message(intro_prompt)
    response = get_last_response()
    blocks_for_word = _humanize_for_word(response, project, report)
    blocks_for_word = _prepend_chapter_heading(blocks_for_word, chapter_title)
    report("Saving original headings and humanized body text to Word.")
    append_result = append_blocks_to_word(blocks_for_word, word_file_path)
    written_sections = 1
    report(append_result)

    while not _contains_chapter_summary(response):
        if written_sections >= MAX_CHAPTER_STEPS:
            raise RuntimeError(
                f"Stopped after {MAX_CHAPTER_STEPS} written responses without finding Chapter Summary."
            )

        report(f"Continuing to the next section ({written_sections + 1}).")
        send_message(CONTINUE_PROMPT)
        response = get_last_response()
        blocks_for_word = _humanize_for_word(response, project, report)
        report("Saving original headings and humanized body text to Word.")
        append_result = append_blocks_to_word(blocks_for_word, word_file_path)
        written_sections += 1
        report(append_result)

    cfg = load_config()
    cfg["projects"][project_name]["current_chapter"] = selected_chapter
    cfg["projects"][project_name].setdefault("outlines", {})[selected_chapter] = chapter_outline
    save_config(cfg)

    return {
        "project": project_name,
        "chapter": selected_chapter,
        "word_file_path": word_file_path,
        "written_sections": written_sections,
        "outline_preview": outline_response[:500],
    }


def write_sections(
    project_name: str = DEFAULT_PROJECT,
    chapter_number: int = DEFAULT_CHAPTER_NUMBER,
    sections_outline: str | None = None,
    progress=None,
) -> dict:
    """
    Write only the section or sections provided in sections_outline.

    The outline may contain one section with multiple subsections, or multiple
    sections with their subsections. Responses are appended to Word until
    ChatGPT emits SECTION_DONE_MARKER.
    """
    if not sections_outline or not sections_outline.strip():
        raise ValueError("Sections outline is required.")

    sections_outline = sections_outline.strip()
    project = get_project(project_name)
    selected_chapter = f"chapter_{chapter_number}"
    word_file_path = project["word_file_path"]

    def report(message: str):
        if progress:
            progress(message)

    report(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(project["chat_url"], project.get("browser", "chrome"))
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    report("Writing the requested section outline.")
    send_message(build_section_prompt(chapter_number, sections_outline))
    response = get_last_response()
    response_for_word = _strip_done_marker(response)
    blocks_for_word = _humanize_for_word(response_for_word, project, report)
    report("Saving original headings and humanized body text to Word.")
    append_result = append_blocks_to_word(blocks_for_word, word_file_path)
    written_responses = 1
    report(append_result)

    while SECTION_DONE_MARKER not in response:
        if written_responses >= MAX_SECTION_STEPS:
            raise RuntimeError(
                f"Stopped after {MAX_SECTION_STEPS} responses without seeing {SECTION_DONE_MARKER}."
            )

        report(f"Continuing requested sections ({written_responses + 1}).")
        send_message(CONTINUE_SECTION_PROMPT)
        response = get_last_response()
        response_for_word = _strip_done_marker(response)
        blocks_for_word = _humanize_for_word(response_for_word, project, report)
        report("Saving original headings and humanized body text to Word.")
        append_result = append_blocks_to_word(blocks_for_word, word_file_path)
        written_responses += 1
        report(append_result)

    cfg = load_config()
    project_cfg = cfg["projects"][project_name]
    project_cfg["current_chapter"] = selected_chapter
    project_cfg.setdefault("section_outlines", {}).setdefault(selected_chapter, []).append(
        sections_outline
    )
    save_config(cfg)

    return {
        "project": project_name,
        "chapter": selected_chapter,
        "word_file_path": word_file_path,
        "written_responses": written_responses,
    }


def humanize_with_stealthwriter(
    text: str,
    project_name: str = DEFAULT_PROJECT,
    mode_name: str | None = None,
    progress=None,
) -> str:
    """
    Humanize text through StealthWriter's website UI.

    The browser profile is persistent, so the first run can be used for manual
    login and later runs should reuse that session.
    """
    project = get_project(project_name)
    return humanize_text(
        text=text,
        browser_name=project.get("browser", "chrome"),
        mode_name=mode_name,
        progress=progress,
    )
