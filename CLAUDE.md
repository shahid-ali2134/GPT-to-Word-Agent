# GPT to Word book agent

Books are written by the `write-book` skill (ChatGPT drafts → StealthWriter humanizes → Word) and
re-humanized by the `rehumanize-book` skill. Project rules: `projects/<project>/brief.md` and
`projects/<project>/work/writer_common.md`. The user talks to the session only through Book Dev
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
5. AI gate before Word: `stealthwriter_check_ai` must be >= 70 (free scans). Red after retry → 🚨
   alert the user.
6. Report every post-humanize change to the user as old → new.

## Repo notes
- `.git` belongs to another Windows user: run git as
  `git -c "safe.directory=F:/Upwork/Portfolio Projects/AI Agents & LLM Systems/GPT to Word Agent" ...`.
- Write Python that contains regex or LaTeX with the Write tool, not a Bash heredoc.
- MCP code changes (mcp_server.py, tools/) load only after the user restarts the MCP server.
