# Standing instructions for every section-writer unit (read fully)

Paths are relative to `projects/book/`. Also follow your agent file and `brief.md`.

## ChatGPT
- Send the prompt you were given verbatim. Rules are already in the chat; don't resend them unless
  ChatGPT clearly breaks one (then resend only that topic via `chatgpt_rules(topic=…, send=True)`).
- If the reply looks cut off, `chatgpt_read_last` first; only then `prompts.complete_truncated`.

## LENGTH RULE (user, 2026-10-14): each chapter at most 25–26 Word pages
- Unit prose budgets (calibrated in Word: 11,039 words rendered at 27 pages): intro ≈ 550
  words; each main section X.1–X.6 ≈ 1,370 words in total (≈ 180 per subsection; fewer when the
  section has many equations); X.7 + X.8 conclusion ≈ 850. Humanizing adds a few percent. Keep every heading, figure, equation and
  table; merge paragraphs so none is only 1–2 lines.
- If ChatGPT's reply is longer, condense it to the budget BEFORE humanizing (same method as
  work/compress_rules.md). Report the prose word count.

## Auto-fix (MCP does the mechanical repairs)
- markdown_to_blocks now auto-fixes and lists them in `autofix`: broken LaTeX escapes, \tag/labels,
  unconvertible LaTeX commands, <text> wrappers, chatter, curly quotes, stray spaces, and figure/table
  numbers (renumbered from Word's next numbers, prose references remapped). Check the list; after
  your own edits run `autofix_blocks` once. Report anything it could not fix.
- chatgpt_send / chatgpt_draw_figure retry once on their own and return `diagnosis`; serious
  failures are pinged to the user automatically. Never message the user yourself (no bookdev_* tools).

## Cleanup known ChatGPT quirks (whatever auto-fix did not cover)
- Strip `<text weight="medium">` wrappers and leftover "Placement:" lines.
- Tab-separated tables are fine if the converter parsed them; otherwise rebuild as rows.
- Equations are never numbered: strip `\tag{}`/labels, rewrite "Equation (N)"/"Eq. N" to positional
  references that point to the right equation.
- Tables are numbered book-wide (Word's numbers), not per chapter: renumber + fix prose references.
- Figure cap: max 5–6 per chapter, about one per section, none in the summary. If ChatGPT puts more
  than 2 figures in one section, keep the best-fitting ones only if prose doesn't depend on the rest;
  otherwise keep them and report. Report the figure count.

## Editing LaTeX in the blocks JSON
- Never edit JSON through Bash heredocs or `python -c` (Git Bash mangles backslashes: `\rho`
  becomes a carriage return + "ho"). Use the Edit tool, or write a Python script file and run it.
- `validate_blocks` now reports control characters; `scan_blocks.py` must print 0.

## Speed
- Right after `markdown_to_blocks` + numbering fixes, draw figures; make edits in few, batched writes.

## Figures
- `chatgpt_draw_figure`, then Read the image: must match caption, spelling correct, legible, not a
  duplicate; up to 3 redraws with specific corrections.
- Every figure/table must be referenced in prose; add the reference sentence BEFORE humanizing.

## Humanize (user's rule: no ChatGPT-worded text in Word)
0. AUTO MODE (after the MCP server restart that loads it; the result then has a `diagnosis` key):
   humanize_blocks(blocks_file, max_words_per_run=4900) diagnoses and fixes small failures itself:
   reloads the StealthWriter page before every run, retries a failed/timed-out/mismatched run once,
   switches failed paragraphs between whole and sentence mode, and keeps paragraphs where every
   sentence contains math as written ("humanize": false + humanize_note; that is accepted, not a
   failure). Make ONE call, report its `diagnosis` in your summary, and only handle what is left in
   not_humanized_blocks / problems. sw_prepare.ps1 is then unnecessary. If the result has no
   `diagnosis` key, the old server is still running: follow steps 1–3 below.
1. Before EVERY humanize_blocks call, run (PowerShell tool):
   `& "F:\Upwork\Portfolio Projects\AI Agents & LLM Systems\GPT to Word Agent\projects\book\work\sw_prepare.ps1"`
   It brings the StealthWriter window to the front and reloads it (F5). Without the reload a result
   left from the previous run makes the tool copy a half-finished new result -> paragraph-count
   mismatch and a wasted credit. If it prints FRONT_ONLY or NO_WINDOW, call `stealthwriter_open`
   and run it again.
2. `humanize_blocks(blocks_file, max_words_per_run=4900)` — one run when the unit fits under
   StealthWriter's 5,000-word limit (second runs on the same page are the ones that misfire).
   If "Could not select StealthWriter mode": `stealthwriter_open`, run sw_prepare.ps1, retry (max 3).
   If `problems` reports a paragraph-count mismatch: run sw_prepare.ps1 and call again once (only the
   not-yet-humanized blocks are sent).
3. If `kept_original_blocks`/`not_humanized_blocks` still non-empty: sw_prepare.ps1, then
   `humanize_blocks(..., sentence_mode=True, max_words_per_run=4900)`.
4. Quota exhausted ("humanizations left" 0 / limit message): STOP and report "QUOTA" — the orchestrator waits for the reset.
5. Touch-up: keep StealthWriter's text. Fix only clearly odd sentences (garbled, ungrammatical,
   broken technical term, British spelling, factually wrong) with fresh wording. Never paste the
   `original` back. No style polishing. Inline math must stay byte-identical.

## Do NOT call docx_append.
Return (short): blocks file; headings; contains Chapter Summary?; complete?; figure/table numbers +
captions; display/inline equation counts; humanized/body counts; ChatGPT rule violations; fixes (≤10 lines).
