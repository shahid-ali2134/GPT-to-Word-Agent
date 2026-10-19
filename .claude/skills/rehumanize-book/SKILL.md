---
name: rehumanize-book
description: Re-humanize the body text of a book that is already in Word through StealthWriter, chapter by chapter, keeping equations, figures, tables, headings and captions untouched, with the user's HUMANIZED TEXT IS FINAL rule and the "Check for AI" gate. Use for "re-humanize the book", "the book fails AI check", "humanize chapter N again".
argument-hint: "[project] [chapter N | all]"
---

# Re-humanize an existing book (user, 2026-10-16; STRICT on every machine and session)

Why: the finished book scored 4-38% human on StealthWriter's "Check for AI" because text had been
edited after humanizing. Chapter 1 redone with this procedure scored 72-100%.

Tools: `projects/<project>/work/rehumanize_book.py` and `style_cleanup.py` (a new project copies
`projects/book1-engineering-intelligent-systems/work/*.py` into its own `work/`). Run them from that `work` folder. The Word file path
is `config.json -> projects.<project>.word_file_path`. Word must be closed when writing.

## Once per book
1. Back up the Word file to `projects/<project>/backups/<timestamp>_before_rehumanize_all.docx`.
2. `python rehumanize_book.py export <docx>` then `python rehumanize_book.py stats` → tell the user
   the word count and the humanizations it needs (about 1 run per 2,400 words), and how many are
   left (shown by every humanize_blocks result; the quota resets daily).

## Per chapter N (in order, from Chapter 1) — refined 2026-10-16 on Chapters 1–5
1. `python rehumanize_book.py prep N 3600` → `rehumanize/chNN.cK.blocks.json` (~3,600 words: one
   StealthWriter run each; formula placeholders count as words, so 4,900 splits into 2 runs). Only
   body prose: inline math and Figure/Table/Section/Chapter references are locked.
2. For each chunk K, ONE run at a time:
   a. `humanize_blocks(project, "work/rehumanize/chNN.cK.blocks.json", max_words_per_run=4900,
      max_tokens_per_paragraph=20, auto=False)`. auto=False: no extra paid run for paragraphs whose
      placeholders got mangled; they are saved as candidates (step 3). Green 70+, "Humanize More"
      max 2x (built in).
   b. `python rh_pairs.py N <chunk> rh_review/chNNcK_pairs.json`, then a read-only reviewer
      subagent with `review_prompt.md` writes `rh_review/chNNcK_fixes.json` (SYMBOL, MEANING incl.
      lost references, UNREADABLE, STYLE asides; fewest-word fixes).
   c. While this chunk's result is still on the page (no scan, no other run in between):
      `stealthwriter_alternatives(project, sentence=<first ~60 chars>)` for each finding; when an
      option (not "Original") fixes it, use it instead of the hand fix (old = the whole sentence).
3. Candidates: `python rh_candidates.py dump N rh_review/chNN_cands.json`, a subagent with
   `candidate_prompt.md` writes `chNN_cands_fixed.json`, then `python rh_candidates.py merge N …`.
4. `python rh_finalize.py N [first_person_fixes.json]`: patches + all fixes; prints FIRST PERSON,
   LOST REFERENCE and CHECK lines. Every one is fixed (fewest words) or justified before writing.
5. Back up Word, `python style_cleanup.py apply <docx> rehumanize_apply` (0 refused), then
   `docx_health(project)`: 0 problems.
6. AI gate: `python rehumanize_book.py scantext N <docx>`, split into ~4,000-word parts
   (`rh_apply_fixes.py` does it), `stealthwriter_check_ai(project, text_file=…)` on each part. Every
   part >= 70. A red part: `python rh_variant.py N k` (pure StealthWriter text of that part) and
   scan it. Raw also red → re-humanize that part (export it from Word, one run), review, write back.
   Raw green → the fixes caused it: replace them with alternatives / fewer words.
7. STRICT FINAL CHECK (mandatory; the per-chunk reviewers missed ~1 problem per 600 words):
   export the finished chapter, pair it with the pre-rehumanize backup
   (rh_review/strict_chNN_pairs.json), a FRESH subagent with `strict_check_prompt.md` → findings,
   another with `strict_fix_prompt.md` → fixes, `python rh_apply_fixes.py N <fixes> <docx>`, rescan
   all parts (>= 70; if one drops, undo that part's fixes).
8. Report to the user on Book Dev: run scores, final Check-for-AI scores per part, counts of fixes
   by kind, anything left unfixed. Wait for the user's GO when they asked to review a chapter.

## Never
- Never edit or rephrase humanized prose beyond the rules above (no polishing, no style fixes).
- Never send headings, captions, tables, display equations or figure text to StealthWriter.
- Never overwrite an existing chunk file (`prep` refuses); never append to Word twice.
