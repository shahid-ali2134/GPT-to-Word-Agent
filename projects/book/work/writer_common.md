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

## ZERO REPETITION (user, 2026-10-14, book-wide; see brief.md)
- No equation, definition, explanation, figure or table may repeat anything already in the book,
  even in other notation (e.g. cosine similarity is defined ONLY in 1.5.3; the chain-rule
  next-token product ONLY in 1.3.3; utilization rho = lambda/(k mu) ONLY in 1.6/2.3.5). Use a
  back-reference and add only new material. ChatGPT often re-derives basics: cut them.
- Before returning, run from projects/book/work: `python dup_check.py <blocks>`,
  `python dup_check_loose.py <blocks>`, `python concept_eq_check.py <blocks>`. Fix every NEW: hit
  (or explain why it is a use, not a redefinition) and report the result.

## RESERVED SYMBOLS (already used in Word; never reuse with a different meaning)
\rho utilization, \lambda arrival rate, \mu service rate (reuse only with these meanings);
\kappa schema compatibility (Ch 2–6, many places), \xi contextual attributes (Ch 4), \upsilon label
coverage (7.5), \varpi cost weight (8.5), \nu halving factor (7.2), \tau processing time (Ch 5),
\psi_j metric functions (7.2), \eta thresholds (7.1), \delta_k paired differences (7.2), \gamma costs,
\pi policy, \Phi validation, \Omega metadata, \phi feature map, g_\omega embedding (2.5.6), \chi
revocation, \zeta certification checks, \theta learned parameters, F freshness, w_t watermark, Q(D)
quality, bold Q/K/V attention (8.2), m attention heads (8.2) and models m_s, m_l (8.5), c context
(8.1/8.3), q tool call (8.4), k top-k (8.2.7), n_shot shots (8.3), T_temp temperature, p_nuc.
Before adding a symbol, Grep `work/ch*/c*r*.blocks.json` and `work/ch0[7-9]/r*.blocks.json` for it.

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
- STYLE MUST VARY (user, 2026-10-14): before drawing, Read the previous 3 figure images in
  `projects/book/figures/` and pick a style from brief.md "Figure styles must vary" that none of
  them uses. Pass it in the prompt: `chatgpt_draw_figure(number=N, prompt="Draw figure N please!
  Style: <style> (not boxes in layers), palette: <colours>. <what to show>")`. Reject and redraw an
  image whose style matches the previous figures. Report the style used.
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
4b. SAVE HUMANIZATIONS (user, 2026-10-15): if StealthWriter only dropped or doubled one or two
   formula placeholders, humanize_blocks now repairs them in place (block gets "math_repaired")
   instead of re-running. Read every math_repaired sentence and move the formula to the right
   spot by hand if needed. Never re-humanize a paragraph just to fix one symbol; fix it manually.
4c. NEVER A FULL RUN FOR 1-2 LINES (user, 2026-10-15): humanize_blocks no longer starts a second
   StealthWriter run for fewer than 300 words. A block left with "needs_manual_finish" keeps its
   first-pass StealthWriter text in "humanized_candidate" (formulas shown as LaTeX): put the
   formulas back by hand, copy it into "text", set "humanized": true, and delete the two helper
   keys. If there is no candidate (run failed), keep the block's text and fix only clearly odd
   sentences by hand; report it. Never call humanize_blocks again for such a block.
4d. SENTENCE ALTERNATIVES (user, 2026-10-15): right after humanize_blocks, for a sentence whose
   meaning or symbols came out WRONG (not merely red), call stealthwriter_alternatives(project,
   sentence=<its start>, new_rounds=0..2) and copy the best option (prefer green, correct meaning)
   into the blocks file by hand. Free, but only for wrong sentences; max 2 new rounds, no loops.
5. Touch-up: keep StealthWriter's text. Fix only clearly odd sentences (garbled, ungrammatical,
   broken technical term, British spelling, factually wrong) with fresh wording. Never paste the
   `original` back. No style polishing. Inline math must stay byte-identical.

## STYLE RULES (user, 2026-10-15; apply as general rules, after humanizing, to every body block)
MINIMAL EDITS: every rewording after humanizing reintroduces AI-detectable text. Change only the
offending punctuation/word and the fewest words around it; never rephrase a whole sentence.
- Impersonal, professional voice: no first or second person (I, we, our, us, you, your, let us).
  Rewrite as "This chapter examined…", "Section 8.1.6 showed…", "the reader/practitioner…".
- No em/en dashes in prose; rebuild the sentence so it reads naturally without them.
- No contractions: it's -> it is, don't -> do not, can't -> cannot (possessives like "system's" stay).
- No colons or semicolons in prose: split into two sentences or join with a proper conjunction
  ("because", "and", "while", "such as"). Keep colons only inside math, times or headings.
- Equation references are positional only ("the equation above", "this equation", "the preceding
  expression"), whichever fits the sentence; never "(24)" or "Equation 24".
- Fix humanizer sentences that make no sense or have major grammar errors (e.g. a misplaced
  "however": "Feedback, however, should not necessarily induce a change" when there is no contrast
  -> "However, feedback does not necessarily require a change in the system."). Leave small
  grammar quirks and odd-but-clear wording alone; never restore ChatGPT's original.
- Symbols in prose are ALWAYS inline LaTeX ($C_q$, $	au_a$, $x^{2}$) so Word shows italic variables
  with real subscripts/superscripts matching the display equation; never plain "Cq", "τa", "x^2".
- Every piecewise or multi-line formula is a display equation ($$ ... egin{cases} ... \end{cases} $$),
  never prose like "Cq = { 1 if Am ≥ τa ..., 0 otherwise" or "left\{beginmatrix ...".
- Layout (docx_writer enforces): one blank line before and after each equation; one blank line
  before each table and after its caption; NO blank line between a table and its caption.

## Do NOT call docx_append.
Return (short): blocks file; headings; contains Chapter Summary?; complete?; figure/table numbers +
captions; display/inline equation counts; humanized/body counts; ChatGPT rule violations; fixes (≤10 lines).
