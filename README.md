# GPT-to-Word Agent

A Python automation tool that writes long-form book content with ChatGPT, humanizes body prose through StealthWriter, and appends the formatted result to a Word document.

There are two ways to run it:

| Mode | Who decides what happens next | Best for |
|------|-------------------------------|----------|
| **Claude Code + MCP** (recommended) | Claude, as an intelligent orchestrator, using the MCP tools in `mcp_server.py` | Whole books, hands-off, with every equation/table/figure verified before it reaches Word. See [Claude Code Orchestration (MCP)](#claude-code-orchestration-mcp). |
| **Discord bot** | Hard-coded workflow in `agent_core.py` | Running individual commands remotely from Discord. See [Discord Commands](#discord-commands). |

Both modes share the same browser automation, StealthWriter integration, Word styling and formatting rules (`/instruct` presets).

---

## How It Works

1. Opens ChatGPT in a Playwright browser using your saved login session.
2. Sends chapter or section prompts, waits for the full response (handles slow/heavy chats automatically).
3. Parses the ChatGPT markdown into typed blocks: chapter title, section headings, subsection headings, body paragraphs, equations, tables, and figure placeholders.
4. Sends body prose to StealthWriter for humanization (headings, equations, tables, and figures are kept as-is).
5. Writes the formatted, humanized output to a `.docx` file using styles defined in `config.json`.
6. For sections that request figures, automatically sends "Draw figure N please!" to ChatGPT, downloads the generated image, and inserts it into Word.

---

## Project Structure

```
GPT-to-Word-Agent/
├── agent_core.py             # Discord workflow logic + the /instruct rules and chapter prompts
├── discord_bot.py            # Discord slash-command front end
├── discord_bridge.py         # Message routing between Discord and agent threads
├── mcp_server.py             # MCP server: tools Claude Code uses to run the book workflow
├── .mcp.json                 # Registers mcp_server.py with Claude Code (server name: book-agent)
├── config.json               # Projects, styles, browser, and StealthWriter settings
├── config.example.json       # Template — copy to config.json and fill in your values
├── requirements.txt
├── .claude/
│   ├── settings.json         # Enables book-agent, tool timeouts, permissions
│   ├── skills/write-book/SKILL.md   # Orchestrator playbook (the workflow, in plain English)
│   └── agents/
│       ├── section-writer.md # Subagent: one ChatGPT response → verified blocks file
│       └── section-auditor.md# Subagent: independent quality gate before Word
├── projects/
│   └── book/
│       ├── brief.md          # Per-book settings and decisions (edit this, not code)
│       ├── ledger.json       # Progress: chapters, units, figures (created at runtime)
│       ├── work/             # Saved ChatGPT replies + blocks JSON per unit (runtime)
│       ├── figures/          # Downloaded figure images (runtime)
│       ├── backups/          # .docx backup before every write (runtime)
│       └── logs/run.log      # Tool activity log (runtime)
└── tools/
    ├── browser_tool.py       # Playwright automation for ChatGPT
    ├── stealthwriter_tool.py # Playwright automation for StealthWriter
    ├── parser.py             # Markdown → typed Block parser (Discord mode)
    ├── word_tool.py          # python-docx formatter + Word COM field updater
    ├── blocks.py             # MCP mode: markdown → editable JSON blocks + validation
    ├── docx_writer.py        # MCP mode: blocks → Word, read-back, backups
    └── __init__.py
```

---

## Claude Code Orchestration (MCP)

Instead of a fixed script, **Claude Code is the orchestrator**. It reads your chapter outline files, drives ChatGPT with your own rules and prompts, checks every response, and writes to Word only when everything passes. It decides what to do when ChatGPT truncates, skips, repeats or misnumbers something, so you don't have to patch code for each new book.

```
┌─────────────────────────────────────────────────────────────┐
│ Claude Code (terminal) — orchestrator                       │
│   skill: write-book        brief: projects/<p>/brief.md     │
│   ledger: projects/<p>/ledger.json (progress / resume)      │
│   ├─ section-writer  subagent (one ChatGPT response)        │
│   └─ section-auditor subagent (independent review)          │
└──────────────────────────┬──────────────────────────────────┘
                           │ MCP tool calls (stdio)
┌──────────────────────────▼──────────────────────────────────┐
│ mcp_server.py  "book-agent" — small deterministic tools     │
│   ChatGPT · StealthWriter · blocks/validation · Word        │
│   (wraps tools/*.py; one long-lived browser session)        │
└─────────────────────────────────────────────────────────────┘
```

### Setup (one time)

1. Install dependencies (adds `mcp` and `Pillow`):
   ```powershell
   pip install -r requirements.txt
   playwright install chromium
   ```
2. Make sure `config.json` has the project (`chat_url`, `word_file_path`, `browser`), see [Setup](#setup).
3. Log in once to ChatGPT and StealthWriter (see [First run](#4-first-run--log-in)); the session in `browser_state.json` is reused.
4. Install [Claude Code](https://docs.claude.com/en/docs/claude-code) and start it **in this folder**:
   ```powershell
   cd "path\to\GPT-to-Word-Agent"
   claude
   ```
5. Approve the `book-agent` MCP server when prompted (it's declared in `.mcp.json` and enabled by `.claude/settings.json`). Check it with `/mcp`; it should show **book-agent · connected** with 14 tools.

To register the server manually instead (e.g. from another folder):
```powershell
claude mcp add book-agent -- python "C:\path\to\GPT-to-Word-Agent\mcp_server.py"
```

### Per-book setup

1. Put the chapter outline files in a folder: `1.txt`, `2.txt`, … (first line = chapter title, then the section list).
2. Edit `projects/<project>/brief.md`: outline folder, target length, numbering policy, quality bar, any book-specific decisions. **This file replaces code tweaks.** For a new book, copy `projects/book/` to `projects/<new>/` and add a matching entry in `config.json`.
3. Use a **single ChatGPT chat for the whole book** (`chat_url`). Context across chapters prevents repeated content, figures and equations. Slow replies in a long chat are expected and handled.

### Running

Just talk to Claude in the terminal:

| You say | What happens |
|---------|--------------|
| `write chapter 1` | Writes chapter 1 end to end |
| `write chapters 2-15` | Writes them in order without stopping |
| `continue` | Resumes from the ledger: first unfinished chapter/unit |
| `redo chapter 4 from unit r05` | Restores the backup taken before r05 and rewrites from there |
| `status` | Ledger + document summary (figures/tables/equations so far) |

You can also invoke the skill explicitly: `/write-book continue`.

Per chapter, Claude follows exactly the `/writecompletechapter` sequence, with your prompts verbatim:

1. Sends your `/instruct all` rules once per chat (read live from `agent_core.py`, so editing them there updates both modes).
2. Outline prompt with the chapter file's text → intro prompt → `continue to the next section!` …
3. After a complete response containing section X.6+, sends the conclude prompt once (remaining sections concise) → stops at the X.8 Chapter Summary.

Each ChatGPT response becomes one **unit** (`r01`, `r02`, …):

1. **section-writer** sends the prompt, completes truncated replies, converts the reply into `work/chNN/<unit>.blocks.json`, checks it against your rules, reviews facts/math/tables, draws each figure and *looks at the image* (redraws up to 3× if it doesn't match the caption or has misspelled labels), humanizes body text, proofreads the humanized text against the original, and validates.
2. **section-auditor** reviews the blocks file with fresh eyes; fixes small issues, or fails it back to the writer.
3. **docx_append** validates again, checks numbering against Word, backs up the `.docx`, writes, verifies Word's counts, and marks the unit written in the ledger.

Claude only stops to ask you when: a login is needed or StealthWriter quota is exhausted, the Word file is open/locked, a figure is still wrong after 3 redraws, a numbering gap's cause can't be found, or a unit fails audit twice.

### Quality gates (enforced in code, not just instructions)

| Check | Where | Effect |
|-------|-------|--------|
| Display + inline equations convert to real Word equations | `validate_blocks` | blocks write |
| Balanced braces, `\left`/`\right`, `\begin`/`\end` | `validate_blocks` | blocks write |
| No equation numbers / no "Equation (N)" references | `validate_blocks` | blocks write |
| Tables rectangular, header row, caption, table number | `validate_blocks` | blocks write |
| Figures have number, caption, readable image file | `validate_blocks` | blocks write |
| Figure/table numbers continue exactly from Word's caption count; no references to non-existent figures/tables | `docx_append` | blocks write |
| Word caption counts rose by exactly the expected amount | `docx_append` | reported |
| No ChatGPT chatter, placeholders, leftover markdown, unbalanced `$` | `validate_blocks` | blocks write |
| Same unit can't be written twice | `docx_append` (ledger) | blocks write |
| Repeated words, space before punctuation, truncated paragraph, Unicode math in prose | `validate_blocks` | warning for Claude |
| Inline math survives humanization (swapped for `KEEPTOKEN`s and restored) | `humanize_blocks` | paragraph kept original if lost |

**Numbering policy:** Word numbers figure and table captions itself, continuously through the book. The number in the text must equal Word's number; a mismatch means something was dropped or duplicated, and the write is refused until the cause is found. Equations are not numbered (a dropped equation would leave an unexplained gap).

### MCP tools reference

| Tool | Purpose |
|------|---------|
| `project_status` | Project settings, ledger, document summary (next figure/table numbers). Called first each session. |
| `ledger_update` | Record chapter/unit status, plan, issues. |
| `chatgpt_open` | Open the book's chat (waits for login). |
| `chatgpt_send` | Send a prompt, wait until the reply has stopped changing, save it as markdown. |
| `chatgpt_read_last` | Read the latest reply without sending (recovery). |
| `chatgpt_rules` | The `/instruct` presets and chapter prompts, live from `agent_core.py`; optionally send verbatim. |
| `chatgpt_draw_figure` | "Draw figure N please!" + download; returns path, size, duplicate check. |
| `markdown_to_blocks` | Saved reply → editable blocks JSON + validation report. |
| `validate_blocks` | All checks above + Word's next figure/table numbers. |
| `humanize_blocks` | One StealthWriter pass over body paragraphs, math-safe; keeps originals for proofreading. |
| `stealthwriter_open` | Open StealthWriter for login after logout / quota reset. |
| `docx_append` | Validate → numbering check → backup → write → verify → ledger. |
| `docx_inspect` | Read back the document: counts, headings, last paragraphs. |
| `docx_restore` | Undo: restore a backup (the current file is backed up first). |

**Blocks format** (`work/chNN/<unit>.blocks.json`), which Claude edits directly:

```json
[
  {"type": "heading2", "num": "2.3", "text": "Data Sources"},
  {"type": "body", "text": "The rate is $\\lambda \\geq 0$ with **bold** and *italic*."},
  {"type": "equation", "latex": "\\Pr(N=k) = \\frac{\\lambda^k e^{-\\lambda}}{k!}"},
  {"type": "table", "number": 5, "caption": "Source types.", "rows": [["Type", "Example"], ["API", "REST"]]},
  {"type": "figure", "number": 12, "gpt_number": 13, "caption": "Sources feeding a lakehouse.", "image": "projects/book/figures/fig_012_v1.png"}
]
```

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `/mcp` doesn't list book-agent | Start `claude` from this folder; approve the server; check `python mcp_server.py` starts without import errors (`pip install -r requirements.txt`). |
| Tool call times out on a very slow chat | `.claude/settings.json` sets `MCP_TOOL_TIMEOUT` to 60 min; raise it if needed. Claude will check `chatgpt_read_last` before resending anything. |
| "is open in Word or locked" | Close the `.docx` in Word, then say `continue`. |
| StealthWriter quota / logged out | Say "open StealthWriter", log in, then `continue`. |
| Something wrong already in Word | Say "restore the backup before unit rNN and redo from there" (`docx_restore`). |
| Don't run the Discord bot and Claude Code at the same time | Both drive the same browser session and Word file. |

---

## Discord Commands

Start the bot:

```powershell
python discord_bot.py
```

---

### `/writecompletechapter`

Write a full chapter from start to finish.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `write_chapter_number` | Yes | Chapter number (e.g. `7`) |
| `outline_file` | Yes | `.txt` file attachment containing the chapter outline |
| `project` | No | Project key from `config.json` (default: `book`) |

**What it does:** Opens ChatGPT, sends the outline, writes the intro, then loops through every section and subsection in the outline, humanizes each response, downloads any figures, and appends everything to the Word document.

---

### `/writecompletechapterv2`

Same as `/writecompletechapter` but batches Word writes every 3 sections for faster overall speed.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `write_chapter_number` | Yes | Chapter number |
| `outline_file` | Yes | `.txt` file attachment with the chapter outline |
| `project` | No | Project key (default: `book`) |

---

### `/writesections`

Write one or more specific sections from an outline (useful for re-writing or resuming part of a chapter).

| Parameter | Required | Description |
|-----------|----------|-------------|
| `write_chapter_number` | Yes | Chapter number these sections belong to |
| `sections_file` | Yes | `.txt` file attachment with only the section(s) to write |
| `project` | No | Project key (default: `book`) |

**Tip:** The `.txt` file can contain just one section (e.g. `7.3 Tool Selection`) or multiple sections — the agent writes them in order.

---

### `/finishchapter`

Resume and complete an in-progress chapter from wherever ChatGPT left off.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `chapter_number` | No | Chapter number (for display only) |
| `project` | No | Project key (default: `book`) |

**Use this when:** A previous `/writecompletechapter` run was interrupted, or ChatGPT stopped mid-chapter.

---

### `/recover`

Re-write any content that was parsed and processed but failed to save to the Word document in a previous run.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `project` | No | Project key (default: `book`) |

---

### `/humanize`

Humanize a block of text through StealthWriter without writing a chapter.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `text_file` | Yes | `.txt` file attachment with the text to humanize |
| `project` | No | Project key (default: `book`) |

---

### `/instruct`

Send a formatting reminder to ChatGPT — use this when GPT starts responding in the wrong format (wrong heading numbers, bullet lists instead of prose, plain-text equations, etc.).

| Parameter | Required | Description |
|-----------|----------|-------------|
| `topic` | Yes | Which formatting rule to remind GPT about (see table below) |
| `message` | No | Extra text appended to the preset, or the full instruction when `topic = custom` |
| `project` | No | Project key (default: `book`) |

**Topics:**

| Topic | What it tells ChatGPT |
|-------|----------------------|
| `all` | Every formatting rule at once — **use this before starting a new chapter** |
| `headings` | Number sections as `## X.Y Title` and subsections as `### X.Y.Z Title`; max 3 levels |
| `prose` | Write body content as full paragraphs — no bullet lists; min 3–4 paragraphs per subsection |
| `equations` | All math in LaTeX: `$$...$$` for display, `$...$` for inline; full backslash commands |
| `figures` | Write `Placement: Insert Figure N here.` then `Fig. N. Caption.` for each figure |
| `tables` | Caption as `Table N. Title` on its own line above the table, then markdown pipe format |
| `length` | Write every concept in full academic detail — no summarizing or compressing |
| `norepeat` | Never repeat any content, equation, figure, or table that already appeared earlier in the chat |
| `summary` | The last section of every chapter must be a Chapter Summary (`## X.Y  Chapter Summary`) |
| `conclude` | When asked to conclude: write only `## X.Y` top-level headings with 1–2 brief paragraphs each, no subsections |
| `custom` | Send only the text you type in the `message` field |

**Example — fix heading numbering:**
```
/instruct topic:headings
```

**Example — full reminder before chapter 8:**
```
/instruct topic:all
```

**Example — custom instruction:**
```
/instruct topic:custom message:Always define every technical term on first use.
```

---

### `/closebrowser`

Save browser state and close both the ChatGPT and StealthWriter browser sessions.

---

## Live Controls During Figure Download

While the agent is waiting for ChatGPT to generate a figure, you can type directly in the Discord channel:

| Message | Effect |
|---------|--------|
| `skip` | Skip this figure and move to the next section (a placeholder is inserted in Word) |
| `wait` | Reset the idle timer and extend the hard deadline by 10 more minutes |

The agent reports progress every 30 seconds, e.g.:
> *"Downloading figure… ChatGPT is generating the image (68s elapsed, up to 531s remaining). Type **skip** to skip this figure, or **wait** to extend the timeout."*

---

## Formatting Rules ChatGPT Must Follow

The agent's parser expects responses in a specific format. Use `/instruct all` before starting a chapter to set these rules. Here is what the agent expects:

### Headings

```
## X.Y  Section Title        ← Level 2 (Heading 2 in Word)
### X.Y.Z  Subsection Title  ← Level 3 (Heading 3 in Word)
```

The decimal number is **required** but will be stripped — Word applies its own auto-numbering.

### Equations

```
Display equation (own line):   $$ \frac{a}{b} = \sum_{i=1}^{n} x_i $$
Inline expression:             The loss $\mathcal{L}(\theta)$ is minimized when…
```

Use full LaTeX with backslash commands. Never write equations as plain text or Unicode symbols.

### Figures

```
Placement: Insert Figure 12 here.
Fig. 12. Core components of the agentic ML pipeline.
```

Figure numbers are **sequential across the whole book** (not chapter-based). The agent reads the placement line, automatically sends "Draw figure 12 please!" to ChatGPT, downloads the image, and inserts it in Word.

### Tables

```
Table 3. Comparison of memory types.

| Type        | Scope       | Persistence |
|-------------|-------------|-------------|
| Short-term  | Single task | Session     |
| Long-term   | All tasks   | Permanent   |
```

Caption goes on its own line **above** the table in the format `Table N. Title` or `Table N: Title`.

---

## Setup

### 1. Install dependencies

```powershell
pip install -r requirements.txt
playwright install chromium
```

### 2. Create `.env`

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=optional_test_server_id_for_instant_sync
```

### 3. Create `config.json`

```powershell
Copy-Item config.example.json config.json
```

Minimum required changes:

```jsonc
{
  "projects": {
    "book": {
      "chat_url": "https://chatgpt.com/c/YOUR_CONVERSATION_ID",
      "word_file_path": "C:\\path\\to\\your\\book.docx",
      "browser": "chrome"
    }
  }
}
```

### 4. First run — log in

The first run opens a visible browser. Log in manually to:

- **ChatGPT** (`chatgpt.com`)
- **StealthWriter** (`stealthwriter.ai`)

Login state is saved to `browser_state.json` (git-ignored). All subsequent runs reuse the saved session automatically.

---

## config.json Reference

### Project settings

| Key | Description |
|-----|-------------|
| `chat_url` | Full URL of the ChatGPT conversation to use |
| `word_file_path` | Full path to the target `.docx` file |
| `browser` | `"chrome"` or `"opera"` |
| `current_chapter` | Tracks the current chapter key (e.g. `"chapter_7"`) |
| `outlines` | Map of chapter keys to outline text |

### `stealthwriter`

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `"Ghost 5.2 Pro"` | StealthWriter humanization mode |
| `timeout_sec` | `180` | Maximum seconds to wait for humanization |
| `human_score_threshold` | `70` | Minimum human-score % before accepting the result |
| `max_rehumanize` | `2` | Maximum Rehumanize retries if score is below threshold |

### `styles`

Defines Word formatting for each block type (`chapter`, `heading2`, `heading3`, `body`). Each entry supports:

| Key | Description |
|-----|-------------|
| `word_style` | Word built-in style name (e.g. `"Heading 2"`, `"Normal"`) |
| `font` | Font family (e.g. `"Garamond"`) |
| `size_pt` | Font size in points |
| `bold` | `true` / `false` |
| `all_caps` | `true` / `false` |
| `alignment` | `"left"`, `"center"`, `"right"`, `"justify"` |
| `space_before` / `space_after` | Paragraph spacing in points |
| `first_line_cm` | First-line indent in cm |
| `hanging_cm` | Hanging indent in cm |

### `page`

Controls Word document page size and margins (all values in cm).

---

## Formatting Behaviour

| ChatGPT output | Block type | Word style |
|----------------|------------|------------|
| `# Chapter X` + title | `chapter` | Heading 1 |
| `## X.Y Title` | `heading2` | Heading 2 |
| `### X.Y.Z Title` | `heading3` | Heading 3 |
| Body paragraph | `body` | Normal |
| `- bullet` / `1. item` | `list_item` | Normal |
| `$$...$$` equation | `equation` | Word OMath object |
| `Placement: Insert Figure N` | `figure_placeholder` | Triggers auto-download |
| `Fig. N. Caption` | `figure_caption` | Normal |
| `Table N. Title` | `table_caption` | Caption |
| Markdown pipe table | `table` | Word table |

**Section numbers are stripped from headings** before writing to Word — Word's multilevel numbering generates them automatically.

**Heading depth is determined by the decimal number**, not the markdown tag. `## 2.1.1 Title` becomes Heading 3; `### 2.1 Title` becomes Heading 2.

**Only `body` blocks are sent to StealthWriter.** Everything else is written to Word as-is.

---

## Files Not Committed

| File / pattern | Reason |
|----------------|--------|
| `.env` | Discord bot token |
| `config.json` | Contains personal chat URLs and file paths |
| `browser_state.json` | Live browser session cookies |
| `browser_profiles/` | Persistent browser profile data |
| `__pycache__/` | Python bytecode |
| `*.docx` | Generated Word documents |
| `projects/*/work/`, `figures/`, `backups/`, `logs/`, `ledger.json` | Book content and runtime state from MCP mode |
| `.claude/settings.local.json` | Personal Claude Code permissions |
