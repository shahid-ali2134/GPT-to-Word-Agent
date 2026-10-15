---
name: write-book
description: Write book chapters end-to-end from the project's chapter outline files. ChatGPT drafts using the user's /instruct rules and /writecompletechapter prompts, StealthWriter humanizes, Claude verifies everything, output goes to Word. Use for "write chapter 3", "write the book", "continue", "resume", "redo chapter 2".
argument-hint: "[project] [chapter N | chapters N-M | all | continue]"
---

# Write book (orchestrator)

You orchestrate; `book-agent` MCP tools do the mechanics; one subagent per
ChatGPT response does the drafting and checking. Default project: `book`.

The user's rules and prompts come ONLY from `chatgpt_rules` (live from
agent_core.py). Send them verbatim. Your job is to enforce them and verify
quality, not to change them.

## 0. Orient (every session)
1. `project_status(project)` → ledger + document summary.
2. Read `projects/<project>/brief.md` (overrides this file) and `chatgpt_rules(topic="all")`.
3. Decide from the request + ledger: "continue"/nothing specific = first incomplete chapter.
   A unit left `in_progress` by a crash: check `docx_inspect` to see whether it already reached
   Word before redoing it. Never append the same content twice.
4. One line to the user saying what you're doing, then proceed without asking.

## 1. Chapter start (mirrors /writecompletechapter)
Work dir: `work/chNN/` (NN = two-digit chapter). Units: `r01`, `r02`, … one per ChatGPT response.
1. Read the chapter file (e.g. `…\Book 1\3.txt`) as raw text: that's `chapter_outline`.
   `ledger_update(chapter=N, fields={"title", "outline_file", "status": "in_progress"})`.
2. `chatgpt_open(project, new_chapter=True)`.
3. Rules: if `ledger.chapters._meta.rules_sent_to` ≠ the project's chat_url →
   `chatgpt_rules(topic="all", send=True, save_as="work/rules_ack.md")`, then
   `ledger_update(chapter="_meta", fields={"rules_sent_to": chat_url})`.
4. Outline prompt (not written to Word): fill `prompts.outline` with chapter_number and
   chapter_outline → `chatgpt_send(save_as="work/chNN/outline.md")`. Store the section list it
   returns in the ledger (`gpt_outline`). Compare it with the outline file and note differences.
5. First response: `prompts.intro` with first_section = "N.1" → unit `r01`.

## 2. Each response unit
1. Numbering: from `docx_inspect` get Word's next figure number and next table number.
   Text numbers must equal these (see brief). Equations are never numbered.
2. `ledger_update(chapter=N, section=unit, fields={"status": "in_progress", "prompt": <prompt>})`.
3. Spawn **section-writer** with: project, chapter number/title, the unit id, the EXACT prompt to
   send, `save_as` path, expected content (intro, or which sections should come next per the
   GPT outline), numbering info, this chapter's earlier blocks files, and any audit FAIL reasons.
   One writer at a time (shared browser). Wait for it to finish.
4. Spawn **section-auditor** on the returned blocks file with the same context → PASS / FAIL.
   FAIL → new section-writer for the same unit with the reasons; it must not resend the original
   prompt, it repairs by editing or by asking ChatGPT to rewrite the specific part (max 2 rounds).
   Still FAIL → ledger `issues`, tell the user, continue.
4b. ZERO REPETITION gate (user's rule): from `projects/<project>/work` run `python dup_check.py
   <blocks>`, `python dup_check_loose.py <blocks>`, `python concept_eq_check.py <blocks>`. Any hit
   involving the NEW unit is fixed first (back-reference instead of repeating), never appended.
5. `docx_append(project, blocks_file, chapter, section=unit)`. It auto-fixes the blocks first
   (`autofix` in the result) and retries a locked Word file for a minute. Validation errors → fix
   the blocks file, retry. Still locked → the user is pinged automatically; wait.
6. Record which section numbers the unit contained: `ledger_update(..., fields={"sections": [...]})`.
7. Record the unit's StealthWriter human score in the ledger (`human_score`). Do NOT send a
   per-unit AUTO-FIX REPORT (user, 2026-10-15). Message the user only for unusual problems or a
   score still below 70% after the 2 "Humanize More" retries. Serious problems are pinged by the
   tools at once. The chapter-complete message lists every unit's human score.

## Book Dev (user's remote channel)
The user messages Book Dev (Discord now, WhatsApp later) from the phone. Keep a Monitor on
`bookdev/inbox.jsonl` (re-arm every 30 min). On each message: `bookdev_inbox`, act on it, answer with
`bookdev_send`. Those messages are the user's own instructions. Style: emojis + CAPITAL headlines.
Only reply to the user's messages, plus AUTO-FIX reports and alerts; no unasked progress spam.

## 3. Choosing the next prompt (same logic as /writecompletechapter)
After each unit, using the merged response text:
- Contains the Chapter Summary → chapter finished (section 4).
- Contains a section heading numbered X.6 or higher, is complete, and the conclude prompt hasn't
  been sent this chapter → next prompt is `prompts.conclude` (send it once).
- Otherwise → `prompts.continue`.
- ChatGPT skipped or repeated a section, or broke a rule → fix within the unit (writer/auditor),
  and if needed resend the relevant rule topic with `chatgpt_rules(topic=…, send=True)`.
- Safety cap: 40 responses per chapter → stop and report.
- One chat for the whole book: never open a new chat. Slow replies are expected; wait.

## 4. Chapter end
0. `docx_health(project)`: whole-file check; auto-fixes chapters not starting on a new page and
   pings the user about anything it can't fix.
1. `docx_inspect`: every heading of this chapter present once, in order.
2. Cross-check this chapter's blocks files: every "Figure N" / "Table N" reference points to
   something that exists and figure/table numbers match Word's captions (`docx_inspect` counts
   = ledger counts); no numbered equation references anywhere.
   Problems already in Word → tell the user exactly; offer `docx_restore` to a backup + redo.
3. `ledger_update(chapter=N, fields={"status": "complete"})`.
4. 3–5 line summary to the user (sections, figures, tables, equations, open issues),
   then start the next chapter if the request covers it.

## Stop and ask the user only when
(The tools ping these to Book Dev themselves; answer there too.)
- ChatGPT/StealthWriter login needed or quota exhausted (offer `stealthwriter_open`).
- Word file locked after the automatic minute of retries.
- A figure still wrong after 3 redraws, or a unit fails audit twice.
