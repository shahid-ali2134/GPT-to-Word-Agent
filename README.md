# GPT-to-Word Agent

A Python automation tool that writes long-form book content with ChatGPT, humanizes body prose through StealthWriter, and appends the formatted result to a Word document — fully automated and controlled from Discord.

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
├── agent_core.py             # Core workflow logic
├── discord_bot.py            # Discord slash-command front end
├── discord_bridge.py         # Message routing between Discord and agent threads
├── config.json               # Projects, styles, browser, and StealthWriter settings
├── config.example.json       # Template — copy to config.json and fill in your values
├── requirements.txt
└── tools/
    ├── browser_tool.py       # Playwright automation for ChatGPT
    ├── stealthwriter_tool.py # Playwright automation for StealthWriter
    ├── parser.py             # Markdown → typed Block parser
    ├── word_tool.py          # python-docx formatter + Word COM field updater
    └── __init__.py
```

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
