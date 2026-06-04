"""
Shared workflow helpers for the ChatGPT to Word agent.
"""

import glob
import json
import os
import re
import shutil
import time

from tools.browser_tool import clear_figure_src_cache, download_last_generated_image, get_last_response, get_message_count, navigate_to_chat, screenshot_figure, send_message
from tools.parser import Block, parse_inline, parse_markdown
from tools.stealthwriter_tool import humanize_text
from tools.word_tool import append_blocks_to_word, has_pending_blocks, recover_pending_blocks, save_pending_blocks

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
    "{chapter_number} before {first_section}. "
    "Begin your response directly with the content. "
    "Do not include any disclaimers, notes, or meta-commentary about the instructions."
)
CONTINUE_PROMPT = "continue to the next section!"
# Used by _fetch_complete only when a response is genuinely truncated at GPT's
# token limit (not a mid-stream read).  Avoids "next section" so GPT finishes
# the current section before moving on.
COMPLETE_TRUNCATED_PROMPT = (
    "The response was cut off mid-sentence. "
    "Please continue writing from exactly where you left off and complete the current section."
)
CONCLUDE_CHAPTER_PROMPT = (
    "Continue to the next section! But as we are at the end of section so lets "
    "conclude the section properly! Only write the main sections now!"
)
MAX_CHAPTER_STEPS = 40
MAX_FINISH_STEPS = 40
SECTION_DONE_MARKER = "[SECTION_WORKFLOW_COMPLETE]"

# ── Formatting instructions sent to ChatGPT via /instruct ────────────────────
# These are written to match the ACTUAL parser logic in tools/parser.py:
#   • heading2 = ## X.Y Title  (HEADING2_NUMBER_RE strips the number for Word)
#   • heading3 = ### X.Y.Z Title (HEADING3_NUMBER_RE strips the number for Word)
#   • No heading4 — config.json only defines chapter/heading2/heading3/body
#   • Tables: any markdown pipe table works (JS extractor converts | to \t)
#     Caption must be on its own line BEFORE the table as "Table N. Title" or "Table N: Title"
#   • Figures: write "Placement: Insert Figure N here." to trigger figure_placeholder;
#     the agent then sends "Draw figure N please!" to ChatGPT automatically.
#     Figure numbers are sequential across the whole book (1, 2, 3 … 12 …), not chapter-based.
#   • Equations: $$...$$ display, $...$ inline — JS extractor reads KaTeX annotation tags

_INSTRUCT_HEADINGS = """\
From now on, always number every section and subsection heading using decimal notation:

• Level 2 sections use double-hash:   ## X.Y  Title
  Example: ## 3.1  Introduction to the Framework

• Level 3 subsections use triple-hash: ### X.Y.Z  Title
  Example: ### 3.1.1  Core Definitions

Rules:
- Always include the number prefix before the title.
- Do NOT write unnumbered headings.
- Do NOT go deeper than X.Y.Z (three levels is the maximum).
- The number will be stripped and replaced by the Word document's own numbering, so include it anyway for clarity.

SUBSECTION DEPTH RULE:
- Every main section (## X.Y) must contain AT LEAST 4 subsections (### X.Y.1, ### X.Y.2, ### X.Y.3, ### X.Y.4).
- This applies to all content sections — for example, if a chapter has 10 sections (1.1 through 1.10), \
sections 1.1 through 1.6 must each have at least 4 subsections (1.1.1–1.1.4, 1.2.1–1.2.4, etc.).
- The final sections of a chapter (typically the last 3–4) may be shorter with fewer or no subsections \
only if they are concluding or summary sections.
- Do NOT write a section as a flat block of paragraphs with no subsections — always break the content \
into labelled subsections.

SECTION INTRODUCTION RULE:
- After every main section heading (## X.Y), write 1–2 introductory paragraphs BEFORE the first \
subsection (### X.Y.1). These paragraphs should introduce and frame what the section covers.
- Do NOT jump directly from ## X.Y to ### X.Y.1 with no text in between.
- Example structure:
    ## 3.2  Perception and Context Interpretation
    [1–2 introductory paragraphs here]
    ### 3.2.1  Sensory Input Processing
    [subsection content]

CHAPTER TITLE — FIRST RESPONSE ONLY:
- In the very first response (the introductory opening paragraphs before any section), \
always begin with the chapter title on its own line using a single hash:
    # Chapter X: Full Chapter Title
- Write the introductory paragraphs immediately after the title, then end your response \
with: "Continue to the next section!"
- Do NOT include the chapter title again in any subsequent section response.\
"""

_INSTRUCT_PROSE = """\
From now on, write all body content as continuous prose paragraphs:

• Do NOT use bullet points, dashes, or numbered lists inside the body text.
• Each subsection should contain at least 3–4 full paragraphs.
• Every paragraph should be 4–6 sentences minimum.
• Reserve bullet lists only for explicitly enumerable items (e.g. a comparison table or step-by-step procedure) — and even then, prefer prose.
• Do NOT begin a response with a preamble like "Here is section 3.1:" — start directly with the heading.
• Do NOT add any closing commentary after finishing a section — no "Section 3.4 is now complete.", \
"Let me know if you'd like changes.", "Shall I continue?", or any similar follow-on sentence. \
Stop immediately after the last paragraph of content.
• ALWAYS write your response directly in the chat. Do NOT use Canvas, document view, \
or any side panel. Everything must appear as a normal chat message.
• In normal prose text (outside of $...$ or $$...$$), do NOT use special symbols or \
Unicode characters (×, →, ≥, ∈, α, β, ∑, etc.). Write them out in plain English words \
instead (e.g. "multiplied by", "leads to", "greater than or equal to", "belongs to", \
"alpha", "beta", "sum"). Special symbols are only permitted inside LaTeX delimiters.\
"""

_INSTRUCT_EQUATIONS = """\
From now on, write every mathematical expression using LaTeX syntax:

• Display equations (on their own line, centred):
  Wrap with double dollar signs:  $$  equation  $$

• Inline expressions embedded in a sentence:
  Wrap with single dollar signs:  $  expression  $

• Use full LaTeX backslash commands inside the delimiters:
  \\frac{a}{b}   \\sum_{i=1}^{n}   \\begin{matrix} ... \\end{matrix}
  \\mathbb{R}    \\mathcal{L}      \\alpha \\beta \\gamma \\delta
  \\left\\{ ... \\right\\}   \\begin{cases} ... \\end{cases}

• NEVER write equations as plain text, Unicode math symbols (×, ∑, ∈, ≤), or words.

EQUATION QUANTITY RULE:
• Include a meaningful number of equations throughout each chapter — do not write sections \
with no equations at all unless the topic is purely conceptual and mathematics genuinely do not apply.
• Vary the number of equations per section according to how mathematical the topic is:
  - Highly technical subsections: 3–5 display equations plus several inline expressions.
  - Moderately technical subsections: 1–3 display equations plus inline expressions where natural.
  - Conceptual subsections with some formalism: at least 1 display equation or definition.
• Do NOT cluster all equations in one section — spread them naturally across the chapter.
• Every equation must be referenced in the surrounding prose (e.g. "as expressed in Equation (N)").\
"""

_INSTRUCT_LENGTH = """\
From now on, write every section and subsection in full academic depth:

• Every subsection must be at least 3–4 complete paragraphs — never a single-paragraph stub.
• Do NOT summarize or compress — expand every concept with:
    1. A precise definition
    2. A clear explanation of why it matters
    3. At least one concrete example or application
    4. Its relationship to other concepts in the chapter
• If your response is approaching the length limit, finish the current paragraph cleanly and stop there.
• Do NOT truncate a sentence — always end on a full stop.\
"""

_INSTRUCT_FIGURES = """\
From now on, follow this exact figure protocol:

Step 1 — placement line (where the figure goes in the text):
  Write on its own line:   Placement: Insert Figure N here.
  Example:                 Placement: Insert Figure 12 here.

Step 2 — caption line (immediately after the placement line):
  Write:   Fig. N. [Descriptive caption text ending with a period.]
  Example: Fig. 12. Core components of the agentic ML pipeline.

Rules:
• Every chapter must contain AT LEAST 4–5 figures spread across its sections.
• Figure numbers are SEQUENTIAL across the whole book (e.g. 10, 11, 12 …), NOT chapter-based (not 3.1, 3.2).
• The agent will automatically ask ChatGPT to draw the figure after detecting the placement line.
• Do NOT write "Draw Figure N" — that command is sent automatically by the agent.
• Do NOT use placeholder text like [Figure N] or (see figure below).

Visual design rules (ChatGPT will draw each figure):
• Every figure must be UNIQUE in style and layout — do NOT repeat the same visual format twice, for example do not always use "infographic" style, use a mixture of stlyes.
• Vary the visual style across figures: use solid-color diagrams for some, gradient fills for others, \
flow charts, architecture diagrams, layered block diagrams, network graphs, timeline visuals, \
heatmaps, or any other distinct visual form that fits the content.
• Make every figure visually attractive and professional — use clean layouts, meaningful color choices, \
clear labels, and good use of whitespace.
• The caption must clearly describe what the figure shows so ChatGPT can draw it accurately.\
"""

_INSTRUCT_TABLES = """\
From now on, follow this exact table protocol:

Step 1 — caption line (ABOVE the table):
  Write:   Table N. [Title of the table.]    — or —    Table N: [Title]
  Example: Table 3. Comparison of agentic architectures.

Step 2 — the table itself (immediately below the caption):
  Use standard markdown pipe format with a header separator row:
  | Column A | Column B | Column C |
  |----------|----------|----------|
  | value    | value    | value    |

Rules:
• Table numbers are sequential within the chapter (Table 1, Table 2, …).
• Do NOT put the caption inside a table cell.
• Do NOT use plain-text tab-separated tables — use the pipe (|) format.\
"""

_INSTRUCT_NOREPEAT = """\
From now on, do NOT repeat any content that has already appeared earlier in this conversation:

• Do NOT restate, paraphrase, or re-explain any concept, definition, or argument \
that was already covered in a previous section or response.
• Do NOT repeat any equation that was already written — if you need to refer to it, \
cite it by its number (e.g., "as shown in Equation (3)").
• Do NOT re-insert any figure or table that was already placed — reference it by \
number only (e.g., "as illustrated in Figure 7" or "see Table 2").
• Each section must introduce genuinely new content that extends and builds on \
what came before, not a restatement of it.
• If a concept was introduced briefly in an earlier section, you may expand on it \
here — but do NOT copy or rewrite the original passage.

Please reply with "Understood." to confirm.\
"""

_INSTRUCT_SUMMARY = """\
From now on, the LAST section of every chapter must be a Chapter Summary:

• Write the final section as a dedicated summary section with the heading:
    ## X.Y  Chapter Summary
  where X is the chapter number and Y is the next section number in sequence.
• The summary must briefly recap the core ideas covered in the chapter — \
one short paragraph per major topic area is sufficient.
• Do NOT introduce any new concepts, equations, figures, or tables in the summary.
• Do NOT use subsections (### headings) inside the Chapter Summary.
• Keep the summary concise: 4–8 paragraphs maximum.

Please reply with "Understood." to confirm.\
"""

_INSTRUCT_ALL = """\
Before I give you the next section to write, please confirm you will follow ALL of these formatting rules for every response in this session:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEADINGS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Level 2 sections:    ## X.Y  Title      (e.g., ## 3.1  Overview)
• Level 3 subsections: ### X.Y.Z  Title   (e.g., ### 3.1.1  Definitions)
• Always include the decimal number prefix.
• Maximum depth is X.Y.Z — no deeper.
• Do NOT write unnumbered headings.
• Every main section (## X.Y) must contain AT LEAST 4 subsections (### X.Y.1 through ### X.Y.4).
  Example: section 1.1 → subsections 1.1.1, 1.1.2, 1.1.3, 1.1.4; section 1.2 → 1.2.1, 1.2.2, 1.2.3, 1.2.4; etc.
  This applies to all content sections. Only the final 3–4 closing/summary sections of a chapter \
may have fewer subsections.
• Do NOT write a section as a flat block of paragraphs — always break content into labelled subsections.
• After every ## X.Y heading, write 1–2 introductory paragraphs BEFORE the first ### X.Y.1 subsection.
  Do NOT jump directly from the section heading to the first subsection with no text in between.
• FIRST RESPONSE ONLY: begin with the chapter title on its own line:
    # Chapter X: Full Chapter Title
  Write the introductory paragraphs immediately after, then end with: "Continue to the next section!"
  Do NOT include the chapter title again in any subsequent section.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSE FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• ALWAYS write your response directly in the chat — do NOT use Canvas, document view, or any side panel.
• Do NOT add closing commentary after finishing a section — no "Section X.Y is now complete.", \
"Let me know if you'd like changes.", "Shall I continue?", or any similar follow-on sentence. \
Stop immediately after the last paragraph of the section.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROSE STYLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Write body content as continuous prose paragraphs — no bullet points or lists in the main text.
• Each subsection must have at least 3–4 full paragraphs (minimum 4–6 sentences each).
• Do NOT start a response with "Here is section X.Y:" — begin directly with the heading.
• In normal prose (outside LaTeX delimiters), do NOT use special symbols or Unicode characters \
(×, →, ≥, ∈, α, β, ∑, etc.). Write them out in plain English words instead \
(e.g. "multiplied by", "leads to", "greater than or equal to", "alpha", "sum").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATHEMATICAL EQUATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Display equations (own line): $$  LaTeX  $$
• Inline expressions:           $  LaTeX  $
• Use full LaTeX: \\frac{a}{b}, \\sum_{i=1}^{n}, \\begin{matrix}…\\end{matrix}, \\mathbb{R}, etc.
• NEVER use plain-text math or Unicode symbols (∑, ×, ∈, ≤…).
• Include equations throughout the chapter — do NOT leave entire sections without any mathematics \
unless the content is purely conceptual.
• Vary the count by how technical the subsection is:
    - Highly technical: 3–5 display equations + inline expressions.
    - Moderately technical: 1–3 display equations + inline expressions where natural.
    - Conceptual with some formalism: at least 1 display equation or formal definition.
• Spread equations across all sections — do NOT cluster them all in one place.
• Every display equation must be cited in the surrounding prose (e.g. "as shown in Equation (N)").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIGURES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Every chapter must contain AT LEAST 4–5 figures spread across its sections.
• Where a figure belongs, write a placement line on its own:
    Placement: Insert Figure N here.
• Immediately after, write the caption:
    Fig. N. [Caption text ending in a period.]
• Figure numbers are SEQUENTIAL across the whole book (e.g., 10, 11, 12 …).
• Do NOT write "Draw Figure N" — the agent handles that automatically.
• Do NOT use placeholder text like [Figure N].
• Every figure must be UNIQUE in style — do NOT repeat the same visual format twice in a chapter.
• Vary styles across figures: solid-color diagrams, gradients, flow charts, architecture diagrams, \
network graphs, timelines, heatmaps, layered blocks, etc.
• Make every figure visually attractive: clean layout, meaningful colors, clear labels, good whitespace.
• Write a detailed enough caption so the figure can be drawn accurately from it alone.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TABLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Write the caption on its own line ABOVE the table:
    Table N. [Title]    — or —    Table N: [Title]
• Use standard markdown pipe format with a header separator row.
• Table numbers are sequential within the chapter (Table 1, Table 2, …).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NO REPETITION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Do NOT repeat any content, equation, figure, or table that has already appeared earlier in this conversation.
• Each section must introduce genuinely new material — not restate or paraphrase prior sections.
• To refer back to something already written, cite it by number (e.g., "as in Equation (3)" or "see Figure 7").

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CHAPTER SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• The LAST section of every chapter must be a Chapter Summary (## X.Y  Chapter Summary).
• Recap the core ideas covered — one short paragraph per major topic area.
• No new concepts, equations, figures, or tables in the summary.
• No subsections inside the Chapter Summary.
• Keep it to 4–8 paragraphs maximum.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETENESS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Write each section completely — do not cut off mid-sentence.
• If approaching the length limit, end at a clean paragraph boundary.
• Do NOT summarize or compress — write every concept in full detail.

Please reply with "Understood." to confirm.\
"""

_INSTRUCT_CONCLUDE = """\
I will sometimes send you this exact prompt:

  "Continue to the next section! But as we are at the end of section so lets \
conclude the section properly! Only write the main sections now!"

When you receive that prompt, follow these rules strictly:

• Write ONLY the remaining top-level section headings using ## X.Y format.
  Example: ## 4.7  Evaluation Metrics    ## 5.8  Future Directions

• For each top-level section, write 1–2 short concluding paragraphs (no more).
  Summarise the key idea of that section briefly and conclusively.

• Do NOT write any subsections (### X.Y.Z) or sub-subsections at all.
  Skip every subsection entirely — only the top-level ## X.Y headings matter.

• Do NOT expand or elaborate — the chapter has already reached its length limit.
  The goal is to close out the remaining sections cleanly without adding new depth.

• Do NOT add a chapter summary or conclusion paragraph after the last section.
  Stop immediately after the last top-level section's 1–2 paragraphs.

Please reply with "Understood." to confirm.\
"""

FORMATTING_INSTRUCTIONS: dict[str, str] = {
    "headings":  _INSTRUCT_HEADINGS,
    "prose":     _INSTRUCT_PROSE,
    "equations": _INSTRUCT_EQUATIONS,
    "length":    _INSTRUCT_LENGTH,
    "figures":   _INSTRUCT_FIGURES,
    "tables":    _INSTRUCT_TABLES,
    "norepeat":  _INSTRUCT_NOREPEAT,
    "summary":   _INSTRUCT_SUMMARY,
    "conclude":  _INSTRUCT_CONCLUDE,
    "all":       _INSTRUCT_ALL,
}


def send_formatting_instruction(
    topic: str,
    project_name: str = DEFAULT_PROJECT,
    custom_message: str = "",
    progress=None,
) -> dict:
    """Send a formatting reminder to ChatGPT for the given project.

    topic         — key in FORMATTING_INSTRUCTIONS, or 'custom' to use custom_message only.
    custom_message — appended to a preset instruction, or used alone when topic='custom'.
    Returns a dict with 'topic', 'instruction_sent', and 'gpt_reply'.
    """
    project = get_project(project_name)

    if progress:
        progress(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(
        project["chat_url"],
        project.get("browser", "chrome"),
        progress=progress,
    )
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    if topic == "custom":
        instruction = custom_message.strip()
    else:
        instruction = FORMATTING_INSTRUCTIONS.get(topic, "")
        if custom_message.strip():
            instruction = instruction + "\n\n" + custom_message.strip()

    if not instruction:
        raise ValueError(f"No instruction text for topic '{topic}' and no custom_message provided.")

    if progress:
        progress(f"Sending '{topic}' formatting instruction to ChatGPT.")
    send_message(instruction, progress=progress)
    reply = get_last_response()

    return {
        "topic": topic,
        "instruction_sent": instruction,
        "gpt_reply": reply,
    }


# ── Figure manual-download bridge ─────────────────────────────────────────────
# Set by discord_bot.py before running any chapter command.  When set, the agent
# will ask the user for help if it cannot auto-download a figure, then wait for
# a reply instead of silently inserting a placeholder.
# Signature: (message: str) -> str | None   (returns user reply, or None on timeout)
_figure_input_fn: "callable | None" = None

# ── Figure interrupt function ──────────────────────────────────────────────────
# Set by discord_bot.py before any chapter command.  Called non-blocking inside
# the figure-download polling loop.  Returns the latest user command ("skip" /
# "wait" / "") so the user can control a long-running DALL-E wait from Discord.
# Signature: () -> str
_figure_interrupt_fn: "callable | None" = None


def configure_figure_input_fn(fn: "callable | None") -> None:
    """Register (or clear) the Discord reply function for manual figure download."""
    global _figure_input_fn
    _figure_input_fn = fn


def configure_figure_interrupt_fn(fn: "callable | None") -> None:
    """Register (or clear) the non-blocking interrupt function for figure downloads."""
    global _figure_interrupt_fn
    _figure_interrupt_fn = fn


def _find_latest_download(max_age_sec: float = 600.0) -> "str | None":
    """Return the path of the most-recently modified image in the user's Downloads folder.

    Only returns a file if it was modified within *max_age_sec* seconds (default 10 min),
    so we don't accidentally grab a stale download from an earlier session.
    """
    downloads = os.path.expanduser("~/Downloads")
    candidates: list[str] = []
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        candidates.extend(glob.glob(os.path.join(downloads, ext)))
    if not candidates:
        return None
    latest = max(candidates, key=os.path.getmtime)
    if time.time() - os.path.getmtime(latest) <= max_age_sec:
        return latest
    return None
# Matches any section heading at position 6 or higher within a chapter:
# 1.6, 2.7, 3.8, 10.9, 4.12, etc.
SECTION_6_RE = re.compile(r"(?m)^\s*(?:#{1,4}|[*]{1,3})?\s*\d+\.([6-9]|\d{2,})\b")
SECTION_PROMPT_TEMPLATE = """Write only the requested part of chapter {chapter_number}.

Use this section outline exactly as the scope:
{sections_outline}

Write the complete prose for every listed section and subsection in this outline.
Do not write content outside this outline.
Do not write the chapter introduction unless it is included in this outline.
Do not write the chapter summary unless it is included in this outline.
If the content is too long, write as much as you can and stop at a clean boundary.
Begin your response directly with the content. Do not include any disclaimers, notes, or meta-commentary about the instructions.
When all requested sections and subsections are fully complete, end your final response with:
{done_marker}"""
CONTINUE_SECTION_PROMPT = (
    "Continue writing the next remaining section or subsection from the provided "
    f"outline. When all requested material is complete, end with {SECTION_DONE_MARKER}"
)
MAX_SECTION_STEPS = 20
CHAPTER_TITLE_RE = re.compile(r"^\s*chapter\s+\d+\.?\s*[:\-]?\s*(.*?)\s*$", re.I)

_PREAMBLE_RE = re.compile(
    r"^(there'?s?\s+a\s+(slight|small|minor)\s+(disconnect|mismatch|issue|note)|"
    r"there\s+is\s+a\s+(slight|small|minor)\s+(disconnect|mismatch|issue|note)|"
    r"(note|please\s+note|just\s+a\s+note)\s*:|"
    r"i\s+(will|shall)\s+proceed|"
    r"i\s+notice[d]?|"
    r"as\s+noted|"
    r"just\s+to\s+clarify|"
    r"before\s+i\s+(begin|start)|"
    r"(it\s+)?seems\s+(like\s+)?there('?s|\s+is)\s+a)",
    re.I,
)


def _resolve_figures(
    blocks: list[Block],
    word_file_path: str,
    progress=None,
) -> list[Block]:
    """
    For every figure_placeholder block, send "Draw figure X please!" to ChatGPT,
    download the generated image, and replace the placeholder with a figure block
    that carries the local image path.  Falls back to keeping the placeholder (with
    a visible [Figure X] marker in Word) if the download fails.
    """
    report = progress or (lambda msg: None)
    figures_dir = os.path.join(os.path.dirname(os.path.abspath(word_file_path)), "figures")
    os.makedirs(figures_dir, exist_ok=True)

    result = list(blocks)
    for i, block in enumerate(result):
        if block.block_type != "figure_placeholder":
            continue

        fig_num = block.figure_number
        if fig_num == 0:
            continue  # malformed placeholder — no figure number detected

        # Wrap the entire per-figure attempt so that any unexpected exception
        # (Playwright crash, screenshot error, etc.) leaves the surrounding
        # section text intact — the placeholder stays and the section is written.
        try:
            _resolve_single_figure(result, i, fig_num, figures_dir, progress, report)
        except Exception as exc:
            report(
                f"Warning: Figure {fig_num} resolution raised an unexpected error "
                f"({exc}). Section text will still be written; placeholder used."
            )

    return result


def _resolve_single_figure(result, i, fig_num, figures_dir, progress, report):
    """Resolve one figure_placeholder: request → download → fallback to manual input."""
    report(f"Requesting figure {fig_num} from ChatGPT.")

    # Record how many assistant messages exist RIGHT NOW so that the download
    # functions never confuse a previously generated figure with the new one.
    baseline = get_message_count()

    # allow_retry=False: DALL-E generation starts silently (no immediate text
    # response), so a retry would send the same prompt twice and confuse GPT.
    send_result = send_message(
        f"Draw figure {fig_num} please!", allow_retry=False, progress=progress
    )
    if send_result.startswith("Error"):
        report(f"Warning: Browser error when requesting figure {fig_num} — skipping.")
        return
    # A "Warning: no immediate response" is expected for DALL-E — proceed to download

    save_path = os.path.join(figures_dir, f"fig_{fig_num:03d}.png")
    report(f"Downloading figure {fig_num}.")
    success = download_last_generated_image(
        save_path, progress=progress, interrupt_fn=_figure_interrupt_fn,
        baseline_msg_count=baseline,
    )

    if success:
        new_block = Block("figure")
        new_block.figure_number = fig_num
        new_block.figure_image_path = save_path
        result[i] = new_block
        report(f"Figure {fig_num} saved to {save_path}.")
        return

    # success is None → user typed "skip" as an interrupt; honour it immediately
    # without prompting again.  success is False → download failed on its own,
    # so offer the manual fallback.
    if success is None:
        report(f"Warning: Figure {fig_num} skipped by user. A placeholder will appear in Word.")
        return

    # ── Ask the user for manual help via Discord ──────────────────────────────
    # This prompt only appears after all automatic attempts have failed
    # (idle timeout + final Phase 3 screenshot) so normal operation is hands-free.
    if _figure_input_fn:
        notify = (
            f"⚠️ **Could not auto-download Figure {fig_num}.**\n"
            f"• Reply **`retry`** to check the screen again right now.\n"
            f"• Reply **`done`** once you have saved the file to your Downloads folder.\n"
            f"• Reply **`wait`** to pause 30 s then retry automatically.\n"
            f"• Reply **`skip`** to insert a placeholder and move on.\n"
            f"_(Waiting up to 5 minutes for your reply)_"
        )
        while True:
            reply = _figure_input_fn(notify)
            if reply is None:
                report(f"Warning: No reply received for Figure {fig_num}. Using placeholder.")
                break
            reply_lower = reply.strip().lower()

            if reply_lower in ("retry", "r"):
                report(f"Retrying screenshot capture for Figure {fig_num}...")
                if screenshot_figure(save_path):
                    new_block = Block("figure")
                    new_block.figure_number = fig_num
                    new_block.figure_image_path = save_path
                    result[i] = new_block
                    report(f"Figure {fig_num} captured via retry screenshot.")
                    success = True
                    break
                notify = (
                    f"📷 Screenshot retry for **Figure {fig_num}** found nothing yet.\n"
                    f"• **`retry`** — check screen again\n"
                    f"• **`wait`** — pause 30 s then retry automatically\n"
                    f"• **`done`** — file is in Downloads\n"
                    f"• **`skip`** — use placeholder"
                )
                continue

            if reply_lower in ("wait", "w"):
                report(f"Waiting 30s then retrying screenshot for Figure {fig_num}...")
                time.sleep(30)
                if screenshot_figure(save_path):
                    new_block = Block("figure")
                    new_block.figure_number = fig_num
                    new_block.figure_image_path = save_path
                    result[i] = new_block
                    report(f"Figure {fig_num} captured after wait.")
                    success = True
                    break
                notify = (
                    f"⏳ Still no figure detected for **Figure {fig_num}**.\n"
                    f"• **`retry`** — check screen again\n"
                    f"• **`wait`** — pause another 30 s\n"
                    f"• **`done`** — file is in Downloads\n"
                    f"• **`skip`** — use placeholder"
                )
                continue

            if reply_lower in ("skip", "no", "n", "s"):
                report(f"Warning: Figure {fig_num} skipped by user. A placeholder will appear in Word.")
                break

            # Any other reply ("done", "ok", …) → try to grab from Downloads
            downloaded = _find_latest_download()
            if downloaded:
                shutil.copy2(downloaded, save_path)
                new_block = Block("figure")
                new_block.figure_number = fig_num
                new_block.figure_image_path = save_path
                result[i] = new_block
                report(f"Figure {fig_num}: grabbed '{os.path.basename(downloaded)}' from Downloads.")
                success = True
            else:
                report(
                    f"Warning: Figure {fig_num} — could not find a recent file in Downloads. "
                    "A placeholder will appear in Word."
                )
            break

    if not success:  # False = download failed; None already handled above
        report(f"Warning: Could not download figure {fig_num}. A placeholder will appear in Word.")


WORD_SAVE_RETRIES = 6
WORD_SAVE_RETRY_DELAY = 10  # seconds between retries (6 × 10 = 60 s total)


def _append_with_retry(blocks: list[Block], word_file_path: str, progress=None) -> str:
    """
    Call append_blocks_to_word with automatic retry on PermissionError
    (Word file open). If all retries are exhausted the blocks are saved to
    a .pending.json file and a clear error is raised.
    """
    report = progress or (lambda msg: None)
    for attempt in range(WORD_SAVE_RETRIES + 1):
        try:
            return append_blocks_to_word(blocks, word_file_path)
        except PermissionError:
            if attempt < WORD_SAVE_RETRIES:
                report(
                    f"Warning: '{os.path.basename(word_file_path)}' is open in Word — "
                    f"please close it. Retrying in {WORD_SAVE_RETRY_DELAY}s "
                    f"(attempt {attempt + 1}/{WORD_SAVE_RETRIES})."
                )
                time.sleep(WORD_SAVE_RETRY_DELAY)
            else:
                save_pending_blocks(blocks, word_file_path)
                raise PermissionError(
                    f"Could not save to '{word_file_path}' after {WORD_SAVE_RETRIES} retries. "
                    "Content saved to a pending file. Close the Word document and run /recover."
                )


def recover_pending(project_name: str = DEFAULT_PROJECT, progress=None) -> dict:
    """
    Write any blocks saved to the pending file back to the project's Word document.
    Safe to call even if no pending file exists.
    """
    project = get_project(project_name)
    word_file_path = project["word_file_path"]

    def report(message: str):
        if progress:
            progress(message)

    if not has_pending_blocks(word_file_path):
        return {
            "project": project_name,
            "word_file_path": word_file_path,
            "message": "No pending content found for this document.",
        }

    report("Recovering pending blocks from last failed write.")
    result_msg = recover_pending_blocks(word_file_path)
    report(result_msg)
    return {
        "project": project_name,
        "word_file_path": word_file_path,
        "message": result_msg,
    }


def _strip_gpt_preamble(text: str) -> str:
    """Remove any leading meta-commentary GPT prepends before the actual content."""
    paragraphs = re.split(r"\n{2,}", text.strip())
    while paragraphs and _PREAMBLE_RE.match(paragraphs[0].strip()):
        paragraphs.pop(0)
    return "\n\n".join(paragraphs).strip()


def _is_thinking_response(text: str) -> bool:
    """Return True when *text* looks like a reasoning/thinking indicator rather than real content.

    Reasoning models (o1, o3, o4-mini) sometimes leak their scratchpad text
    through the DOM walker.  If we detect that the response is essentially
    just a thinking marker we skip humanization and Word writing entirely.
    """
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) < 80:
        # Very short response consisting only of reasoning noise words
        if re.match(
            r"^(thinking|reasoning|analyzing|processing|working on it|"
            r"let me think|I'?m thinking|one moment)\.{0,3}$",
            stripped, re.I,
        ):
            return True
    return False


def _concat_dedup(base: str, continuation: str) -> str:
    """Concatenate *base* + *continuation*, removing a repeated leading heading.

    When GPT truncates mid-section and is asked to continue, it often re-states
    the section heading at the start of the continuation.  This removes that
    duplicate so the heading does not appear twice in the Word document.

    Also handles mid-word splits: if the base ends without whitespace or sentence
    punctuation (e.g. ends with "ge") and the continuation starts with a lowercase
    letter (e.g. "nerate…"), the two fragments are joined directly (no paragraph
    break) so "generate" is reconstructed rather than split across paragraphs.
    """
    if not continuation or not continuation.strip():
        return base

    # Find the last heading block in *base*
    last_heading = None
    for block in reversed(parse_markdown(base)):
        if block.block_type in ("chapter", "heading2", "heading3"):
            last_heading = block.plain_text.strip().lower()
            break

    if last_heading:
        groups = re.split(r"\n{2,}", continuation.strip())
        if groups:
            first_clean = re.sub(r"^#{1,4}\s*", "", groups[0]).strip().lower()
            if first_clean == last_heading:
                groups = groups[1:]
                continuation = "\n\n".join(groups).strip()

    # Mid-word join: base ends on an incomplete word fragment and continuation
    # starts with a lowercase letter — glue directly without inserting a newline.
    base_tail = base.rstrip()
    cont_head = continuation.lstrip()
    if (base_tail and cont_head
            and not re.search(r'[\s.!?)\]"`\'»—,;:]$', base_tail)
            and cont_head[0].islower()):
        return (base_tail + cont_head).strip()

    return (base + "\n\n" + continuation).strip()


def _fetch_complete(response: str, progress=None, max_extra: int = 3) -> str:
    """If *response* is truncated, silently continue and merge until complete.

    Sends up to *max_extra* COMPLETE_TRUNCATED_PROMPT messages (NOT the normal
    "next section" prompt — that would make GPT skip ahead instead of finishing
    the current section).  Each continuation is merged via _concat_dedup so the
    final result is a single coherent block.  The merged response is what gets
    written to Word — no duplicate or truncated sections.
    """
    for _ in range(max_extra):
        if not _is_response_truncated(response) or _contains_chapter_summary(response):
            break
        if progress:
            progress("Response appears cut off — fetching continuation to complete the current section.")
        send_message(COMPLETE_TRUNCATED_PROMPT, progress=progress)
        cont = _strip_gpt_preamble(get_last_response())
        response = _concat_dedup(response, cont)
    return response


def _demote_chapter_to_heading2(blocks: list[Block]) -> list[Block]:
    """Demote all chapter-level blocks to heading2 (for section/continue responses)."""
    return [Block("heading2", b.runs) if b.block_type == "chapter" else b for b in blocks]


def _fix_extra_chapter_blocks(blocks: list[Block]) -> list[Block]:
    """After chapter title is prepended, demote any additional chapter blocks to heading2."""
    result = []
    chapter_seen = False
    for block in blocks:
        if block.block_type == "chapter":
            if chapter_seen:
                result.append(Block("heading2", block.runs))
            else:
                chapter_seen = True
                result.append(block)
        else:
            result.append(block)
    return result


def _normalize_chapter_opening(blocks: list[Block], chapter_title: str) -> list[Block]:
    """
    Remove GPT's chapter label block(s) so _prepend_chapter_heading can add the
    correct clean title from the outline.

    GPT commonly outputs one or both of:
      # Chapter 2                        ← bare label (no title)
      # Chapter 2: From Automation …     ← label + title (must ALSO be removed)
      ## From Automation to Agency       ← title repeated as heading2
    All of these are stripped; _prepend_chapter_heading then adds the clean title.
    """
    result = list(blocks)

    # Remove every leading chapter block whose text matches "Chapter N[: ...]"
    # — covers both the bare label and the "Chapter N: Title" variant.
    while result and result[0].block_type == "chapter":
        if CHAPTER_TITLE_RE.match(result[0].plain_text.strip()):
            result.pop(0)
        else:
            break  # not a "Chapter N" pattern → keep

    # Remove a leading heading2/3 that exactly duplicates the chapter title
    if result and result[0].block_type in ("heading2", "heading3"):
        block_text = result[0].plain_text.strip().lower()
        title_text = chapter_title.strip().lower()
        if block_text == title_text:
            result.pop(0)

    return result


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _first_section(chapter_number: str, chapter_outline: str) -> str:
    marker = f"{chapter_number}.1"
    return marker if marker in chapter_outline else f"{chapter_number}.1"


def _is_response_truncated(text: str) -> bool:
    """Return True if the response appears to be cut off mid-generation.

    A complete GPT response ends with sentence-closing punctuation, a
    closing delimiter, or a standalone heading/list line.  A bare word,
    comma, or conjunction indicates truncation.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return False
    last = lines[-1].strip()
    # Ends with sentence punctuation, closing bracket/quote, code-fence,
    # equation delimiters ($$), or heading/list marker.
    return not re.search(
        r'[.!?)\]"`\'»—]$'   # sentence punctuation and closers
        r'|\$\$$'             # display-equation closing $$
        r'|^#{1,4}\s'         # heading line
        r'|```$'              # code fence
        r'|\*{3}$',           # bold/italic closer
        last,
    )


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


_MATH_BODY_RE = re.compile(
    # LaTeX backslash patterns
    r"\\[a-zA-Z]+[\{\( ]"
    r"|_\{|\^\{|\$\$|\\left|\\right"
    # Unicode math operators that essentially never appear in plain prose
    r"|[∑∏∫∬∭∮∧∨∀∃∄∈∉∋⊂⊃⊆⊇⊕⊗⊙⊘∓√∞∂∇≡≅≃≈∼≜]"
    # Double-struck / blackboard-bold letters used in math
    r"|[ℝℕℤℚℂℙ𝔼𝟙𝟘]"
)


def _is_math_body(text: str) -> bool:
    """True when a body paragraph contains math and must not be humanized."""
    return bool(_MATH_BODY_RE.search(text))


def _humanize_for_word(text: str, project: dict, progress=None) -> list[Block]:
    if not text or not text.strip():
        return []
    if _is_thinking_response(text):
        return []  # reasoning/thinking scratchpad — not real content

    original_blocks = parse_markdown(text)
    if not original_blocks:
        return []

    body_indexes = [
        index for index, block in enumerate(original_blocks)
        if block.block_type == "body"
        and block.plain_text.strip()
        and not _is_math_body(block.plain_text)
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

    # Reset figure-src exclusion list once per chapter so cross-section deduplication works.
    # (Clearing inside _resolve_figures was wrong — it wiped Figure 1's src before Figure 2.)
    clear_figure_src_cache()

    report(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(
        project["chat_url"],
        project.get("browser", "chrome"),
        progress=progress,
    )
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    outline_prompt = build_outline_prompt(chapter_number, chapter_outline)
    report("Requesting the chapter outline from ChatGPT.")
    send_message(outline_prompt, progress=progress)
    outline_response = get_last_response()

    intro_prompt = build_intro_prompt(chapter_number, chapter_outline)
    report("Writing the introductory paragraphs.")
    send_message(intro_prompt, progress=progress)
    response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
    blocks_for_word = _humanize_for_word(response, project, report)
    blocks_for_word = _normalize_chapter_opening(blocks_for_word, chapter_title)
    blocks_for_word = _prepend_chapter_heading(blocks_for_word, chapter_title)
    blocks_for_word = _fix_extra_chapter_blocks(blocks_for_word)
    blocks_for_word = _resolve_figures(blocks_for_word, word_file_path, report)
    report("Saving original headings and humanized body text to Word.")
    append_result = _append_with_retry(blocks_for_word, word_file_path, report)
    written_sections = 1
    report(append_result)

    while not _contains_chapter_summary(response):
        if written_sections >= MAX_CHAPTER_STEPS:
            raise RuntimeError(
                f"Stopped after {MAX_CHAPTER_STEPS} written responses without finding Chapter Summary."
            )

        # Switch to the concluding prompt once GPT has written section 6 or
        # higher (1.6, 2.7, 3.8 …) so the chapter wraps up properly.
        if _response_reached_section_6(response) and not _is_response_truncated(response):
            next_prompt = CONCLUDE_CHAPTER_PROMPT
        else:
            next_prompt = CONTINUE_PROMPT

        report(f"Continuing to the next section ({written_sections + 1}).")
        send_message(next_prompt, progress=progress)
        # Merge any truncated continuation before writing — prevents the same
        # section heading from appearing twice in the Word document.
        response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
        blocks_for_word = _humanize_for_word(response, project, report)
        blocks_for_word = _demote_chapter_to_heading2(blocks_for_word)
        blocks_for_word = _resolve_figures(blocks_for_word, word_file_path, report)
        report("Saving original headings and humanized body text to Word.")
        append_result = _append_with_retry(blocks_for_word, word_file_path, report)
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


def write_complete_chapter_v2(
    project_name: str = DEFAULT_PROJECT,
    chapter_number: int = DEFAULT_CHAPTER_NUMBER,
    chapter_outline: str | None = None,
    progress=None,
    batch_size: int = 3,
) -> dict:
    """
    Same as write_complete_chapter but batches Word writes every *batch_size*
    sections (default 3) instead of after every single section.

    Sections are fetched and processed (humanize, figures) one at a time as
    before, but the COM append call only happens once per batch — reducing
    overhead and keeping the document in a cleaner state between writes.
    Any sections left in the buffer at the end are flushed automatically.
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

    clear_figure_src_cache()

    report(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(
        project["chat_url"],
        project.get("browser", "chrome"),
        progress=progress,
    )
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    outline_prompt = build_outline_prompt(chapter_number, chapter_outline)
    report("Requesting the chapter outline from ChatGPT.")
    send_message(outline_prompt, progress=progress)
    outline_response = get_last_response()

    # ── Introductory paragraphs (section 1) ────────────────────────────────────
    intro_prompt = build_intro_prompt(chapter_number, chapter_outline)
    report("Writing the introductory paragraphs.")
    send_message(intro_prompt, progress=progress)
    response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
    blocks = _humanize_for_word(response, project, report)
    blocks = _normalize_chapter_opening(blocks, chapter_title)
    blocks = _prepend_chapter_heading(blocks, chapter_title)
    blocks = _fix_extra_chapter_blocks(blocks)
    blocks = _resolve_figures(blocks, word_file_path, report)

    pending_blocks: list = list(blocks)
    sections_in_batch = 1
    written_sections = 1

    # ── Continue until chapter summary ────────────────────────────────────────
    while not _contains_chapter_summary(response):
        if written_sections >= MAX_CHAPTER_STEPS:
            raise RuntimeError(
                f"Stopped after {MAX_CHAPTER_STEPS} written responses without finding Chapter Summary."
            )

        if _response_reached_section_6(response) and not _is_response_truncated(response):
            next_prompt = CONCLUDE_CHAPTER_PROMPT
        else:
            next_prompt = CONTINUE_PROMPT

        report(f"Continuing to the next section ({written_sections + 1}).")
        send_message(next_prompt, progress=progress)
        response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
        blocks = _humanize_for_word(response, project, report)
        blocks = _demote_chapter_to_heading2(blocks)
        blocks = _resolve_figures(blocks, word_file_path, report)

        pending_blocks.extend(blocks)
        sections_in_batch += 1
        written_sections += 1

        is_last = _contains_chapter_summary(response)
        if sections_in_batch >= batch_size or is_last:
            report(f"Saving {sections_in_batch} section(s) to Word.")
            append_result = _append_with_retry(pending_blocks, word_file_path, report)
            report(append_result)
            pending_blocks = []
            sections_in_batch = 0

    # Flush any sections remaining in an incomplete batch
    if pending_blocks:
        report(f"Saving remaining {sections_in_batch} section(s) to Word.")
        append_result = _append_with_retry(pending_blocks, word_file_path, report)
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

    clear_figure_src_cache()

    report(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(
        project["chat_url"],
        project.get("browser", "chrome"),
        progress=progress,
    )
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    report("Writing the requested section outline.")
    send_message(build_section_prompt(chapter_number, sections_outline), progress=progress)
    response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
    response_for_word = _strip_done_marker(response)
    blocks_for_word = _humanize_for_word(response_for_word, project, report)
    blocks_for_word = _demote_chapter_to_heading2(blocks_for_word)
    blocks_for_word = _resolve_figures(blocks_for_word, word_file_path, report)
    report("Saving original headings and humanized body text to Word.")
    append_result = _append_with_retry(blocks_for_word, word_file_path, report)
    written_responses = 1
    report(append_result)

    while SECTION_DONE_MARKER not in response:
        if written_responses >= MAX_SECTION_STEPS:
            raise RuntimeError(
                f"Stopped after {MAX_SECTION_STEPS} responses without seeing {SECTION_DONE_MARKER}."
            )

        report(f"Continuing requested sections ({written_responses + 1}).")
        send_message(CONTINUE_SECTION_PROMPT, progress=progress)
        response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
        response_for_word = _strip_done_marker(response)
        blocks_for_word = _humanize_for_word(response_for_word, project, report)
        blocks_for_word = _demote_chapter_to_heading2(blocks_for_word)
        blocks_for_word = _resolve_figures(blocks_for_word, word_file_path, report)
        report("Saving original headings and humanized body text to Word.")
        append_result = _append_with_retry(blocks_for_word, word_file_path, report)
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


def _response_reached_section_6(text: str) -> bool:
    """Return True if the response contains a section-6 heading (e.g. 4.6, 2.6, 15.6)."""
    return bool(SECTION_6_RE.search(text))


def finish_chapter(
    project_name: str = DEFAULT_PROJECT,
    chapter_number: int | None = None,
    progress=None,
) -> dict:
    """
    Continue an in-progress chapter from the current GPT position to completion.

    Sends 'continue to the next section!' repeatedly. When a response contains a
    section-6 heading (X.6), sends the concluding prompt once, writes the final
    response, and stops. Chapter Summary is also honoured as an early-exit signal.
    """
    project = get_project(project_name)
    word_file_path = project["word_file_path"]

    def report(message: str):
        if progress:
            progress(message)

    clear_figure_src_cache()

    report(f"Opening ChatGPT chat for project '{project_name}'.")
    navigate_result = navigate_to_chat(
        project["chat_url"],
        project.get("browser", "chrome"),
        progress=progress,
    )
    if navigate_result.lower().startswith(("warning", "error")):
        raise RuntimeError(navigate_result)

    written_sections = 0

    while True:
        if written_sections >= MAX_FINISH_STEPS:
            raise RuntimeError(
                f"Stopped after {MAX_FINISH_STEPS} responses without reaching section 6 "
                "or a Chapter Summary."
            )

        report(f"Continuing to the next section ({written_sections + 1}).")
        send_message(CONTINUE_PROMPT, progress=progress)
        response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)

        blocks_for_word = _humanize_for_word(response, project, report)
        blocks_for_word = _demote_chapter_to_heading2(blocks_for_word)
        blocks_for_word = _resolve_figures(blocks_for_word, word_file_path, report)
        report("Saving to Word.")
        append_result = _append_with_retry(blocks_for_word, word_file_path, report)
        written_sections += 1
        report(append_result)

        if _contains_chapter_summary(response):
            report("Chapter summary detected. Chapter complete.")
            break

        # Only trigger the conclude phase when section 6 is fully written.
        # If the response was truncated mid-way we just keep continuing.
        if _response_reached_section_6(response) and not _is_response_truncated(response):
            report("Section 6 reached. Sending concluding prompt.")
            send_message(CONCLUDE_CHAPTER_PROMPT, progress=progress)

            # The concluding response may itself be truncated — keep going until done.
            while True:
                response = _fetch_complete(_strip_gpt_preamble(get_last_response()), report)
                blocks_for_word = _humanize_for_word(response, project, report)
                blocks_for_word = _demote_chapter_to_heading2(blocks_for_word)
                blocks_for_word = _resolve_figures(blocks_for_word, word_file_path, report)
                report("Saving final sections to Word.")
                append_result = _append_with_retry(blocks_for_word, word_file_path, report)
                written_sections += 1
                report(append_result)

                if _contains_chapter_summary(response):
                    report("Chapter summary detected. Chapter complete.")
                    break

                if not _is_response_truncated(response):
                    report("Concluding response complete. Chapter done.")
                    break

                if written_sections >= MAX_FINISH_STEPS:
                    break

                report("Concluding response appears truncated — requesting continuation.")
                send_message(CONTINUE_PROMPT, progress=progress)

            break

    return {
        "project": project_name,
        "chapter": f"chapter_{chapter_number}" if chapter_number else None,
        "word_file_path": word_file_path,
        "written_sections": written_sections,
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
