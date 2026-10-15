# Draft fewest-word fixes for strict-check findings (write one JSON file; do not touch Word)

Inputs: a findings file (list of {id, cat, phrase, should}) and the matching pairs file (list of
{id, now, math_now, before, math_before}); "now" is the exact current Word text, inline equations as
[[M1]]… (symbol text in math_now; numbers may differ from "before", compare by symbol).

For each finding in the allowed categories, draft the MINIMAL fix in "now": change the fewest words
(typically 1-4: swap, insert or delete), keep the sentence structure and StealthWriter's surrounding
wording; a verbless fragment may get 1-3 words to become a sentence. A lost Section reference is put
back with the fewest words (e.g. "the stage function [[M1]]" -> "the stage function [[M1]] of
Section 3.1.2"). Every [[Mk]] stays exactly once (prefer swapping words to moving tokens). New words:
no dashes, colons, semicolons, contractions or first person; US spelling. If a finding is not a real
error on careful reading, skip it and say why.

Output: the fixes file named in the task, a JSON list of
{"id": int, "cat": "...", "old": "<exact substring of now, unique in that paragraph, as short as possible>", "new": "..."}.
Verify with a Python script (Write tool, not a heredoc) that each old occurs exactly once in its now
and every [[Mk]] remains exactly once after all replacements (apply them in order). Reply with the
count and a compact table: id | old -> new.
