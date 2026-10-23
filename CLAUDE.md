# GPT to Word book agent

Books are written by the `write-book` skill (ChatGPT drafts → StealthWriter humanizes → Word) and
re-humanized by the `rehumanize-book` skill. Project rules: `projects/<project>/brief.md` and
`projects/<project>/work/writer_common.md`. The user talks to the session only through Nexus
(Discord): answer with `bookdev_send`.

## HUMANIZED TEXT IS FINAL (user, 2026-10-16; STRICT, every book, session and machine)
Every reworded sentence after StealthWriter brings AI detection back (proven: 91% → 14% human).
1. All editing and the style rules (no first person, dashes, contractions, colons/semicolons,
   numbered equation references) happen on ChatGPT's text BEFORE humanizing.
2. One StealthWriter run at a time; green 70+; "Humanize More" max 2x, then accept (no loops).
3. Afterwards only: dashes → comma, contractions expanded, first-person words replaced with the
   fewest words, lost formula placeholders put back, British spelling → American (user, 2026-10-16:
   organisation → organization, analyse → analyze, behaviour → behavior, modelling → modeling,
   towards → toward; one word for one word). Symbols, equations, figures and tables never
   change.
4. Only SYMBOL (definition on the wrong symbol), MEANING (reversed/wrong claim, number, reference)
   and UNREADABLE sentences are fixed: StealthWriter sentence alternatives first
   (`stealthwriter_alternatives`, while the result is on the page), else the fewest words (1-4),
   never the structure. Clunky and odd-but-clear wording stay as they are.
5. AI gate before Word: `stealthwriter_check_ai` must be >= 70 (free scans). Below 70 → do NOT
   ask (user, 2026-10-20): automatically "Humanize More" the unit's current humanized body text
   (max 2 rounds, back up the audited version first), redo the allowed post-humanize fixes, re-audit,
   re-check. Only if still < 70 after round 2 → 🚨 alert the user. Tell the user afterwards.
6. Report every post-humanize change to the user as old → new.

## CODE LISTINGS (user, 2026-10-19; every book)
ChatGPT's code goes to Word as a `code` block (Consolas, gray shaded box, thin border) exactly as
written: never humanized, reworded or AI-scanned. Checked for correctness like equations.

## VENDOR-NEUTRAL (user, 2026-10-19; every book)
No vendor, product or framework names in code or prose (OpenAI, Anthropic, Google, LangChain, a
specific SDK, API or model name, OPENAI_API_KEY ...): use generic interfaces such as
`call_model(instructions, history, tools)` "that wraps whichever model service is used (a
commercial API or a locally hosted model)". Tell ChatGPT this; fix any vendor mention BEFORE
humanizing.

## FEW SECTION REFERENCES, MORE CONTENT (user, 2026-10-23; every book)
No repetition still holds, but avoid repeated content by writing NEW material, not by piling up
"as in Section X.Y.Z" references. At most one back-reference per subsection, and only where the
reader truly needs the earlier definition or equation. Never put lists of sections in one
sentence, and never write a paragraph that mostly points elsewhere. Tell ChatGPT this before each
chapter (together with the no-repeat note), and cut extra references BEFORE humanizing.

## SELF-SUFFICIENT: DIAGNOSE AND FIX ERRORS YOURSELF (user, 2026-10-22; every book and session)
Operate as a self-working, self-sufficient agent. This covers EVERY step of every workflow
(write-book, rehumanize-book, the orchestrator and every subagent): ChatGPT, StealthWriter
(humanize, alternatives, Check for AI), figures, validation, Word, Discord/Nexus, MCP tools and
scripts. When a step fails, diagnose and fix it on your own end before involving the user:
1. Look at the real state first: screenshot the page / read its visible error text (StealthWriter
   failures save `bookdev/sw_fail_*.png` plus any limit/quota/login text in the error), read the
   log (`projects/<project>/logs/run.log`), retry once.
2. Fix what you can: split text that exceeds a word limit into smaller parts, reload or reopen the
   page, re-run the step, patch the tool code (tell the user an MCP restart loads it).
3. Alert the user (🚨) only for what truly needs them (login, payment/subscription, a locked Word
   file), and say exactly what the page showed, never a guess from a generic error.

## NEXUS UPDATES: SAME BEHAVIOR EVERY SESSION (user, 2026-10-23; every book, session, PC restart)
The user should never have to ask for status. Without being asked, send via `bookdev_send`:
1. On session start: read `bookdev_inbox`, answer it, then one line on where the book stands and
   what happens next. Then continue the work (unless the ledger's `pause_after_chapter` or a
   pause note says to hold).
2. A progress update at 25%, 50%, 75% and 100% of every chapter (after r02, r04 and r06 of 8,
   then the chapter-complete summary). Each one lists every unit's status, AI score,
   figure/table numbers and old → new audit fixes. This applies after resumes and pauses too.
3. One short line each time a unit reaches Word, and right away for any 🚨 problem
   (login, quota, locked file), followed by ✅ RESOLVED once it is fixed.
4. Keep both Monitors armed (Nexus `sh bookdev_watch.sh`; re-arm on every expiry).

## Repo notes
- `.git` belongs to another Windows user: run git as
  `git -c "safe.directory=F:/Upwork/Portfolio Projects/AI Agents & LLM Systems/GPT to Word Agent" ...`.
- Write Python that contains regex or LaTeX with the Write tool, not a Bash heredoc.
- MCP code changes (mcp_server.py, tools/) load only after the user restarts the MCP server.
