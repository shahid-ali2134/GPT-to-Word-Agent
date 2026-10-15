# Broken-sentence review of one humanized chunk (read-only on Word; write one JSON file)

Input: a pairs file (made by `python rh_pairs.py <NN> <chunk.blocks.json> <pairs.json>`). Each item:
id, "now" = new StealthWriter-humanized paragraph (inline equations shown as [[M1]], [[M2]]…),
"before" = previous version (meaning reference only; same [[Mk]] numbering = same equation),
"math" = each [[Mk]]'s symbol text.

The user's STRICT rule: humanized text is final. Find ONLY publish-blocking problems in "now":
- A SYMBOL: definition attached to the wrong symbol vs "before" (check symbol by symbol using
  "math"), a symbol left undefined that was defined before, a symbol twice where one is meant, a
  definition with a gap like "at time ," or "is the value of .".
- B MEANING: reversed or clearly wrong technical claim vs "before" (negation flipped, wrong
  comparison, swapped term, wrong number, wrong Section/Figure/Table/Chapter reference).
- C UNREADABLE: cannot be parsed however it is read (non-words, misspellings, missing words,
  fragments without a subject or verb, label-colon fragments like "Technical metadata: schemas…",
  doubled words, two sentences run together without punctuation).
- D STYLE: first or second person, contractions, dashes, or a personal aside StealthWriter invented
  ("Actually,", "I believe…", "I'm not sure…").
- Every Section/Figure/Table/Chapter reference in "before" must still be in "now" with the same
  number (a lost or changed reference is category B).
Read EVERY paragraph completely, sentence by sentence; a second, independent strict check of the
finished chapter found ~1 missed problem per 600 words when this list was shorter.
Ignore everything else: clunky or odd-but-clear wording, mild grammar slips, British spelling,
colons/semicolons, word choice, him/her. Do not pad.

For each finding draft the MINIMAL fix: change the fewest words (typically 1-4: swap, insert or
delete words), keep the sentence structure and the surrounding wording; a fragment may get a few
words to become a sentence. Every [[Mk]] stays exactly once (prefer swapping words to moving
tokens). New words: no dashes, colons, semicolons, contractions or first person; US spelling.

Output: the fixes file named in the task, a JSON list of
{"id": int, "cat": "A"|"B"|"C", "sentence": "<full broken sentence as in now>",
 "old": "<exact substring of now, unique in that paragraph, as short as possible>", "new": "<replacement>"}.
Verify with a Python script (written with the Write tool, not a shell heredoc) that each "old"
occurs exactly once in its "now" and every [[Mk]] remains exactly once after all replacements.
Reply with TOTAL A/B/C and a compact table: id | cat | old -> new.
