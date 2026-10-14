# Project brief: book

Project-specific settings. Change this file, not code, for a new book.

## Source
- Book title: Engineering Intelligent Systems From Data Pipelines to Autonomous AI Agents
- Target length: ~350 pages (15 chapters, ~23 pages each).
- Chapter outline files: `F:\Upwork\Books\Books of October 2026\Book 1\` named `1.txt` … `15.txt`.
  The file's full text is what gets pasted into the outline prompt, exactly as the user did by hand.
- Word document + ChatGPT chat: `config.json` → `projects.book` (see `project_status`).

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
  send the conclude prompt once; from then on sections are concise exactly as the rules say,
  ending with X.8 Chapter Summary.
- Outline files with more than 7 content sections (user's decision, ch1): accept ChatGPT merging the
  extra topics into the last content sections as subsections, so every chapter stays 8 sections.
  Don't ask ChatGPT to exceed X.8. Just check that no outline topic was dropped.

## Word layout (user's decisions, 2026-10-14)
- Every chapter starts on a new page with its chapter title heading (the `chapter` block = Heading 1,
  auto-numbered by the template). docx_writer sets page-break-before on every chapter heading after
  the first; verify after appending a chapter's first unit.
- Blank line before and after every equation, figure and table; for figures and tables the blank
  line comes after the caption, never between object and caption.
- Tables use "Grid Table 4 - Accent N", cycling accents 1-6 through the book.
- Run all chapters back to back until the user says stop.

## Figures per chapter (user's decision, 2026-10-14)
- Maximum 5–6 figures per chapter, spread across the content sections (roughly one per section,
  none in the Chapter Summary). Never 5 in one section.
- Chapter 1 exception: section 1.1 already has 5 (Figures 1–5); sections 1.2–1.7 get only 2–3 more
  in total, so chapter 1 ends with 7–8 figures.
- The /instruct figures preset still says "AT LEAST 4–5 figures"; the cap is given to ChatGPT as a
  short extra note before the next prompt rather than by editing the preset.

## Chapter length: 25–26 Word pages (user's decision, 2026-10-14)
- The book must be about 350–400 pages for 15 chapters, so EVERY chapter is at most 25–26 pages in
  Word (measured with `work/page_count.py` / `work/compress_tools.py render`).
- That is about 11,000 prose words per chapter: intro ≈ 600, each of X.1–X.6 ≈ 1,550 (≈ 200 per
  subsection), X.7 + X.8 ≈ 900. All sections X.1–X.8 and all subsections X.X.X stay; figures (5–6),
  equations and tables stay; paragraphs merged so none is only 1–2 lines.
- Chapters 1–7.2 (written before this rule, 429 pages in total) are being compressed to this size
  from their blocks files (`work/compress_rules.md`), re-humanized, and the Word file rebuilt from
  `archive/base_front_matter.docx`. The full version is kept in `archive/`.
- For new units: ChatGPT gets the length rule (work/length_rule.md); a reply longer than the unit
  budget is condensed by the writer BEFORE humanizing.

## Figure styles must vary (user's decision, 2026-10-14)
- Every figure gets a named visual style, rotating through this list so no two figures within
  three of each other share a style, each with its own colour palette:
  flowchart/swimlane, layered stack, timeline, cycle/loop, matrix/heatmap, hub-and-spoke,
  side-by-side comparison, sequence diagram, funnel, tree/hierarchy, quadrant chart,
  isometric 3D, data chart (line/bar).
- The draw prompt names the style explicitly ("Draw figure N please! Style: <style>, palette:
  <colours>, …"); the figure check rejects an image in the same style as the previous figures.

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
- Grammar, spelling and punctuation flawless (US English).
- Equations: valid LaTeX that converts to a Word equation, mathematically correct, symbols defined, notation consistent within the chapter.
- Tables: accurate, rectangular, header row, caption, referenced in prose.
- Figures: the image matches its caption, all text in it spelled correctly and legible, not a duplicate; up to 3 redraws with a specific correction prompt, then escalate. Never insert a wrong figure.
- No ChatGPT chatter, placeholders, leftover markdown, or content repeated from earlier in the book.
- Facts accurate; nothing invented.

## Humanization (StealthWriter)
- Body paragraphs only (never headings, equations, tables, captions), one pass per response.
- User's rule (2026-10-14): humanize ALL body text and use it. No ChatGPT-worded paragraph goes to
  Word; math-heavy paragraphs are humanized around the math (`sentence_mode=True`).
- Afterwards adjust only the very odd sentences (garbled, ungrammatical, broken term, British
  spelling, factually wrong) with fresh wording. Never restore ChatGPT's original phrasing, and
  don't polish style.
- Quota exhausted / logged out → stop and tell the user (`stealthwriter_open` helps them log in).

## Autonomy
- Run chapter after chapter without asking. Stop only for: login/quota, Word file locked,
  a figure still wrong after 3 redraws, a numbering gap whose cause can't be found, or a
  response that fails audit twice.
