---
name: rehumanize-book
description: Re-humanize the body text of a book that is already in Word through StealthWriter, chapter by chapter, keeping equations, figures, tables, headings and captions untouched, with the user's HUMANIZED TEXT IS FINAL rule and the "Check for AI" gate. Use for "re-humanize the book", "the book fails AI check", "humanize chapter N again".
argument-hint: "[project] [chapter N | all]"
---

# Re-humanize an existing book (user, 2026-10-16; STRICT on every machine and session)

Why: the finished book scored 4-38% human on StealthWriter's "Check for AI" because text had been
edited after humanizing. Chapter 1 redone with this procedure scored 72-100%.

Tools: `projects/<project>/work/rehumanize_book.py` and `style_cleanup.py` (a new project copies
`projects/book/work/*.py` into its own `work/`). Run them from that `work` folder. The Word file path
is `config.json -> projects.<project>.word_file_path`. Word must be closed when writing.

## Once per book
1. Back up the Word file to `projects/<project>/backups/<timestamp>_before_rehumanize_all.docx`.
2. `python rehumanize_book.py export <docx>` then `python rehumanize_book.py stats` → tell the user
   the word count and the humanizations it needs (about 1 run per 2,400 words), and how many are
   left (shown by every humanize_blocks result; the quota resets daily).

## Per chapter N (in order, from Chapter 1)
1. `python rehumanize_book.py prep N` → `rehumanize/chNN.cK.blocks.json`, ~2,500 words each (the
   user's chunk size; pass another size only if the user says so). Only body prose is in them:
   inline math and Figure/Table/Section/Chapter references are locked, so StealthWriter cannot
   change symbols or numbers.
2. For each chunk K, ONE StealthWriter run at a time:
   a. `humanize_blocks(project, "work/rehumanize/chNN.cK.blocks.json", max_words_per_run=2500,
      max_tokens_per_paragraph=20)`. Green 70+, "Humanize More" max 2x (built in). Never a full run
      for one or two leftover lines (built in; such blocks keep their current Word text).
   b. Broken-sentence check of the chunk (compare each block's `text` with its `export_text`; a
      subagent may do this read-only): SYMBOL (definition on the wrong symbol: compare the symbols,
      not the [[Mk]] numbers), MEANING (reversed/wrong claim, number, reference), UNREADABLE.
      Nothing else counts; clunky, British spelling and StealthWriter's own colons stay.
   c. While this chunk's result is still on the page: `stealthwriter_alternatives(project,
      sentence=<start of the sentence>, new_rounds=0..2)` for each finding; copy the option that
      fixes it into the chunk file (green dot preferred). If none works: change the fewest words
      (1-4) in the chunk file, never the sentence structure. Keep the $[[Mk]]$ / $Figure N$ spans.
3. `python rehumanize_book.py patch N` → applies the allowed mechanical fixes (dashes,
   contractions) and prints first-person hits: fix those in `rehumanize_apply/chNN.patches.json`
   with the fewest words. It refuses paragraphs whose formula placeholders were lost or misspelled
   (fix them in the chunk file and patch again).
4. Back up Word, then `python style_cleanup.py apply <docx> rehumanize_apply --dry-run`, then
   without `--dry-run`. Every paragraph must be patched, 0 refused (a refusal means Word changed
   since the export: export again and redo the patch for that chapter).
5. `docx_health(project)`: 0 problems; equation and figure counts unchanged.
6. AI gate: `python rehumanize_book.py scantext N <docx>` then `stealthwriter_check_ai(project,
   text_file="work/rehumanize/chNN.scan.txt")`. Every part must be >= 70. A red part: find the
   paragraphs that were hand-fixed in it and replace those hand fixes by StealthWriter
   alternatives; still red → 🚨 alert the user with the score.
7. Report to the user on Book Dev: run scores, Check-for-AI scores, every post-humanize change as
   old -> new, and any finding left unfixed. Wait for the user's GO when they asked to review a
   chapter; otherwise continue with the next chapter.

## Never
- Never edit or rephrase humanized prose beyond the rules above (no polishing, no style fixes).
- Never send headings, captions, tables, display equations or figure text to StealthWriter.
- Never overwrite an existing chunk file (`prep` refuses); never append to Word twice.
