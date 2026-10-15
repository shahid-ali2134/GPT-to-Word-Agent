# Put formulas back into StealthWriter candidates (write one JSON file; do not touch Word)

Input: a candidates file from `python rh_candidates.py dump <NN> <out.json>`: list of {id, candidate,
before, math, missing}. "candidate" is StealthWriter's humanized paragraph in which some
inline-equation placeholders ([[M1]]…) got lost, duplicated or turned into words ("keeper token 2");
"before" has every placeholder in the right place; "math" gives each placeholder's symbol text.

For each item produce "text" = the candidate with EVERY placeholder of "before" present exactly once
and attached to the correct meaning, AND every Section/Figure/Table/Chapter reference of "before"
present with the same number (StealthWriter drops those together with the placeholders). Keep
StealthWriter's wording: only insert/move/delete placeholders and references, plus at most 1-3
connecting words where a definition needs them. Remove duplicates and placeholder junk. Fix a
SYMBOL/MEANING/UNREADABLE error or an invented first-person aside with the fewest words. Change
nothing else. New words: no dashes, colons, semicolons, contractions or first person.

Output: the file named in the task, [{"id": int, "text": "..."}]. Verify with a Python script (Write
tool, not a heredoc) that each text has exactly the same multiset of [[Mk]] as its "before" and every
reference of "before". Reply with one line per id: what was placed where.
