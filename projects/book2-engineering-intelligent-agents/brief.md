# Project brief: book2-engineering-intelligent-agents

Project-specific settings. Change this file, not code, for a new book.
Set up 2026-10-19 from Book 1's brief: every general rule carries over, Book 1's one-off history
(chapter 1 figure exception, compression of chapters 1-7.2) does not.

## Source
- Book title: Engineering Intelligent Agents: Designing, Orchestrating, Optimizing, and Deploying
  Agentic AI Systems
- Book folder (user's catalog): `F:\Upwork\Books\Books of October 2026\Book 2\`
  - Full outline from the user: `TM - Engineering Intelligent Agents.txt` (4 Parts, 15 chapters).
  - Chapter outline files: `1.txt` … `15.txt` (split from the full outline, Book 1 format).
    The file's full text is what gets pasted into the outline prompt, exactly as for Book 1.
  - Word file: `Engineering Intelligent Systems From Data Pipelines to Autonomous AI Agents.docx`
    (the file keeps Book 1's name, but its title page is Book 2's title).
- Word document + ChatGPT chat: `config.json` → `projects.book2-engineering-intelligent-agents`.
- Parts (from the outline): Part I Designing Agents (ch 1-4), Part II Orchestrating Agents (ch 5-8),
  Part III Optimizing Agents (ch 9-11), Part IV Deploying Agents (ch 12-15).
- Target length: same as Book 1 unless the user says otherwise, ~25-26 Word pages per chapter
  (~350-400 pages for 15 chapters).

## One ChatGPT chat for the whole book (user's decision)
- Always the chat in config.json. Never start a new chat: ChatGPT needs the full book context
  so it doesn't repeat content, figures or equations.
- The chat will get slow as the book grows. That's accepted: wait as long as it takes.
  `chatgpt_send` already waits until the reply has stopped changing; never resend a prompt just
  because a reply is slow. If a reply looks cut off, use `chatgpt_read_last` first to see whether
  it was still generating, before sending the complete-truncated prompt.

## ChatGPT rules: the user's own, verbatim
- The rules are the `/instruct` presets in `agent_core.py`, via `chatgpt_rules(topic="all")`.
  Never paraphrase, extend or soften them. Sent verbatim once per chat; resend one topic
  (e.g. `topic="figures"`) if ChatGPT starts breaking it.
- Chapter prompts are the user's, verbatim (`chatgpt_rules` → `prompts`):
  outline → intro → "continue to the next section!" … → conclude prompt → until Chapter Summary.
- Sections: full depth through X.6. Once a response containing section X.6 (or higher) is complete,
  send the conclude prompt once; from then on sections are concise exactly as the rules say.
- OPEN (ask the user before chapter 1): Book 2's outline gives exact section titles and 6-9
  sections per chapter (ch2 has 6, ch3/10/12/15 have 9). Book 1 forced every chapter to 8 sections
  ending with X.8 Chapter Summary. Decide whether Book 2 keeps the outline's sections exactly
  (plus a summary) or follows the Book 1 rule.

## Word layout (user's decisions for Book 1, 2026-10-14)
- Every chapter starts on a new page with its chapter title heading (the `chapter` block = Heading 1,
  auto-numbered by the template). docx_writer sets page-break-before on every chapter heading after
  the first; verify after appending a chapter's first unit.
- Blank line before and after every equation, figure and table; for figures and tables the blank
  line comes after the caption, never between object and caption.
- Tables use "Grid Table 4 - Accent N", cycling accents 1-6 through the book.
- Run all chapters back to back until the user says stop.
- OPEN: whether the Part I-IV titles appear in Word (e.g. a Part page before chapters 1, 5, 9, 12).

## Figures per chapter (user's decision, 2026-10-14)
- Maximum 5–6 figures per chapter, spread across the content sections (roughly one per section,
  none in the Chapter Summary). Never 5 in one section.
- The /instruct figures preset still says "AT LEAST 4–5 figures"; the cap is given to ChatGPT as a
  short extra note before the next prompt rather than by editing the preset.

## Chapter length: 25–26 Word pages (user's decision, 2026-10-14)
- Every chapter is at most 25–26 pages in Word (measured with `work/page_count.py` /
  `work/compress_tools.py render`).
- That is about 11,000 prose words per chapter: intro ≈ 600, each full-depth section ≈ 1,550
  (≈ 200 per subsection), concise sections + summary ≈ 900. All outline sections and subsections
  stay; figures (5–6), equations and tables stay; paragraphs merged so none is only 1–2 lines.
- For new units: ChatGPT gets the length rule (work/length_rule.md); a reply longer than the unit
  budget is condensed by the writer BEFORE humanizing.

## Figure styles must vary (user's decision, 2026-10-14)
- Every figure gets a named visual style, rotating through this list so no two figures within
  three of each other share a style, each with its own color palette:
  flowchart/swimlane, layered stack, timeline, cycle/loop, matrix/heatmap, hub-and-spoke,
  side-by-side comparison, sequence diagram, funnel, tree/hierarchy, quadrant chart,
  isometric 3D, data chart (line/bar).
- The draw prompt names the style explicitly ("Draw figure N please! Style: <style>, palette:
  <colors>, …"); the figure check rejects an image in the same style as the previous figures.

## Numbering (user's decision)
- **Caption numbers in the text must equal Word's caption numbers** for figures AND tables.
  Word numbers captions continuously through the book, so the next figure/table in the text must be
  `next_figure_number` / `next_table_number` from `validate_blocks` / `docx_inspect`.
- A mismatch means something was dropped or duplicated. Don't just renumber: find out why
  (a figure/table missing from this or the previous response, a skipped placement line, a
  duplicate) and fix the cause. Renumber only when ChatGPT simply used its own chapter-based
  table numbering; then update every prose reference to match.
- `docx_append` refuses to write if numbers don't line up, and verifies Word's counts after writing.
- **Equations are not numbered.** No labels. Rewrite any "Equation (N)" / "Eq. N" reference to a
  positional one ("the equation above", "the preceding expression"). Validation enforces this.

## Quality bar (Claude's checks before anything is written to Word)
- Grammar, spelling and punctuation flawless (American English: organization, analyze, behavior,
  modeling, toward).
- Equations: valid LaTeX that converts to a Word equation, mathematically correct, symbols defined, notation consistent within the chapter.
- Tables: accurate, rectangular, header row, caption, referenced in prose.
- Figures: the image matches its caption, all text in it spelled correctly and legible, not a duplicate; up to 3 redraws with a specific correction prompt, then escalate. Never insert a wrong figure.
- No ChatGPT chatter, placeholders, leftover markdown, or content repeated from earlier in the book.

## ZERO REPETITION, BOOK-WIDE (user, 2026-10-14)
Nothing in the book may repeat anything already in it: no equation (even with renamed symbols or a
different form), no re-explained concept or definition, no figure showing the same thing, no table
with the same content. A later section that needs an earlier idea gives a back-reference
("Section 1.5.3") and adds only what is new. Before every docx_append run, with the unit's blocks
file: `python work/dup_check.py <blocks>`, `python work/dup_check_loose.py <blocks>` and
`python work/concept_eq_check.py <blocks>`. Every NEW: hit is fixed (replace with a back-reference
or new material) or explained as a pure use of an earlier definition, not a redefinition.
- Facts accurate; nothing invented.

## Humanization (StealthWriter)
- Body paragraphs only (never headings, equations, tables, captions), one pass per response.
- Humanize ALL body text and use it. No ChatGPT-worded paragraph goes to Word; math-heavy
  paragraphs are humanized around the math (`sentence_mode=True`).
- HUMANIZED TEXT IS FINAL (user, 2026-10-16; full rule in CLAUDE.md and work/writer_common.md).
  All editing and style rules happen on the ChatGPT text BEFORE humanizing. Afterwards only
  mechanical fixes (dashes, contractions, first-person words, British → American spelling) and
  fixes of SYMBOL / MEANING / UNREADABLE sentences, via StealthWriter's sentence alternatives first,
  else the fewest words. Then the "Check for AI" gate (stealthwriter_check_ai, >= 70).
- Quota exhausted / logged out → stop and tell the user (`stealthwriter_open` helps them log in).

## Autonomy
- Run chapter after chapter without asking. Stop only for: login/quota, Word file locked,
  a figure still wrong after 3 redraws, a numbering gap whose cause can't be found, or a
  response that fails audit twice.
