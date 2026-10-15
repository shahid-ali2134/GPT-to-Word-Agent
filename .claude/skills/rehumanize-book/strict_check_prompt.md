# Strict final check of one re-humanized chapter (READ-ONLY: report, change nothing)

Input: a pairs file. Each item: id, "now" = the paragraph as it is in Word now (final), "math_now" =
its inline equations' symbol text by placeholder ([[M1]]…), "before" = the version before
re-humanizing (meaning reference), "math_before". Placeholder NUMBERS may differ between the two
versions: compare by symbol text, never by number.

You are the last gate before publication. Read EVERY paragraph of "now" completely and report:
- A SYMBOL: a symbol defined/described differently than before, a definition attached to the
  wrong symbol, a symbol defined twice, a symbol that was defined before and now is not, a gap where
  a symbol or word is missing ("is the value of .", "at time ,").
- B MEANING: reversed or wrong technical claim, wrong comparison or number, a Section/Figure/Table/
  Chapter reference that is missing, changed or wrong compared with before.
- C UNREADABLE: cannot be parsed however it is read (garbled words, non-words, fragments without a
  verb, doubled words, sentence joined without punctuation).
- D STYLE RULE: first or second person (I, we, our, us, you, your), contractions, em/en dashes, a
  personal aside invented by StealthWriter ("I believe…", "Actually,"). Mechanical only.
Do NOT report clunky or odd-but-clear wording, mild grammar slips, British spelling, colons or
semicolons, or word choice. Do not pad; a precise short list is the goal.

Output: write the JSON file named in the task as a list of
{"id": int, "cat": "A"|"B"|"C"|"D", "phrase": "<exact problematic text from now>", "should": "<what it should say, <=15 words>"}
and reply with TOTAL A/B/C/D counts and the list as id | cat | phrase -> should.
