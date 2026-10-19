# Compressing a chapter to 25–26 Word pages (user's decision, 2026-10-14)

Source: `work/chNN/rXX.blocks.json` (the units already in the book, humanized).
Output: `work/chNN/crXX.blocks.json`, one per source unit, same order. Never edit the source files.

## Keep exactly (user's instruction)
- Every heading block (`chapter`, `heading2`, `heading3`): same text, same `num`, same order.
  All main sections X.1–X.8 and all subsections X.X.X stay.
- Every `equation`, `figure` and `table` block: unchanged (latex, image, caption, rows, numbers),
  in the same subsection and the same order as in the source.

## Condense the prose (body blocks) to the unit's word budget
- Budget per chapter ≈ 11,000 prose words total (intro ≈ 600; each of the six main-section units
  ≈ 1,550; the X.7 + X.8 conclusion unit ≈ 900). The orchestrator gives each unit its exact budget.
- Each subsection: one or two solid paragraphs. NO paragraph shorter than about 60 words: merge short
  paragraphs into their neighbours (the user does not want 1–2 line paragraphs).
- Each section heading keeps one short opening paragraph before its first subsection.
- Every equation stays introduced and explained: one lead-in sentence before it (can end a
  paragraph) and one compact explanation paragraph after it that defines the symbols (merge the
  "where …" definitions into that paragraph). Keep inline math byte-identical (`$...$`).
- Every figure and table must still be referenced in the prose with its number ("Figure 12",
  "Table 3"), placed before or near the object.
- Keep: key definitions, the main argument of each subsection, worked numbers that explain an
  equation, and back-references to earlier sections ("Section 2.4.5"). Cut: repetition, long
  examples, lists of similar items, restatements of earlier chapters, filler transitions.
- No new facts, no new symbols, no new figures or tables. Do not change meaning.
- Book style: academic prose, no bullet lists, no en/em dashes, no "you/your", no contractions, no
  "e.g."/"etc."/"and/or"/slashed word pairs, US spelling, straight quotes.

## Block fields
- Body blocks you write: `{"type": "body", "text": ...}` only (no `humanized`, `original`,
  `humanize` fields): every one is re-humanized through StealthWriter afterwards (user's rule: no
  AI wording in Word).
- Write JSON only with a Python script file or the Write tool (never Bash heredocs or `python -c`:
  Git Bash mangles backslashes, \rho becomes CR + "ho").
- Check each output: `python work/scan_blocks.py <file>` prints 0; `validate_blocks` has 0 errors
  (numbering errors about figures/tables are expected while Word does not yet hold the earlier
  chapters: ignore only those); `python work/compress_tools.py words work/chNN c` shows the budget met
  (within ±10%).
