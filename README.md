# GPT-to-Word Agent

GPT-to-Word Agent is a Python automation tool that writes long-form book content with ChatGPT, humanizes body prose through StealthWriter, and appends the formatted result to a Word document — fully automated, end-to-end.

It supports a CLI workflow and Discord slash commands.

## Features

- Opens ChatGPT in a visible Playwright browser session and reuses saved login state.
- Sends chapter or section prompts to ChatGPT and waits for the full response.
- Parses ChatGPT markdown output into typed blocks: chapter title, section headings, subsection headings, body paragraphs, and artifacts (tables, figures, equations).
- Correctly classifies heading depth from the **section number** (e.g. `2.1` → Heading 2, `2.1.1` → Heading 3) regardless of which HTML tag ChatGPT uses.
- Strips ChatGPT preamble and disclaimers automatically before writing to Word.
- Correctly isolates the chapter title from bare `Chapter X` labels that ChatGPT includes in its responses.
- Sends only body prose to StealthWriter in one batched pass per ChatGPT response.
- After humanization, checks the human-score shown by StealthWriter. If the score is below the configured threshold, clicks Rehumanize automatically — up to a configurable maximum number of retries — before writing to Word.
- Keeps headings, figure placement notes, tables, and equations out of StealthWriter.
- Writes formatted output to `.docx` using Word styles and font settings defined in `config.json`.
- Supports Discord slash commands for full chapter writing, section writing, standalone humanization, and closing the browser.

## Project Structure

```
GPT-to-Word-Agent/
├── agent.py                  # CLI entry point
├── agent_core.py             # Core workflow logic (write chapter, write sections, humanize)
├── discord_bot.py            # Discord slash-command front end
├── config.json               # Projects, styles, browser and StealthWriter settings
├── config.example.json       # Template — copy to config.json and fill in your values
├── requirements.txt
└── tools/
    ├── browser_tool.py       # Playwright automation for ChatGPT
    ├── stealthwriter_tool.py # Playwright automation for StealthWriter humanizer
    ├── parser.py             # Markdown → typed Block parser
    ├── word_tool.py          # python-docx formatter, applies styles from config.json
    └── __init__.py
```

## Commands

### CLI

```powershell
python agent.py
```

| Command | Description |
|---|---|
| `/writeCompleteChapter` | Write a full chapter from outline to Word |
| `/humanize` | Humanize pasted text through StealthWriter |
| `/close` | Save browser state and close |

### Discord

```powershell
python discord_bot.py
```

| Slash command | Description |
|---|---|
| `/writecompletechapter` | Write a full chapter; upload outline as `.txt` attachment |
| `/writesections` | Write specific sections; upload section outline as `.txt` attachment |
| `/humanize` | Humanize uploaded text through StealthWriter |
| `/closebrowser` | Save browser state and close |

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
playwright install chromium
```

2. Create `.env` (Discord bot only):

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=optional_test_server_id
```

3. Create `config.json` from the example:

```powershell
Copy-Item config.example.json config.json
```

4. Edit `config.json` — minimum required changes:

```jsonc
{
  "projects": {
    "book": {
      "chat_url": "https://chatgpt.com/c/YOUR_CONVERSATION_ID",
      "word_file_path": "C:\\path\\to\\your\\book.docx",
      "browser": "chrome"   // or "opera"
    }
  }
}
```

## Browser Login

The first run opens a visible browser window. Log in manually to:

- ChatGPT (`chatgpt.com`)
- StealthWriter (`stealthwriter.ai`)

The agent stores cookies and local storage in `browser_state.json` (git-ignored). Subsequent runs reuse the saved session automatically.

## config.json Reference

### `stealthwriter`

| Key | Default | Description |
|---|---|---|
| `mode` | `"Ghost 5.2 Pro"` | StealthWriter humanization mode |
| `timeout_sec` | `180` | Maximum seconds to wait for humanization |
| `human_score_threshold` | `70` | Minimum human-score % to accept without retrying |
| `max_rehumanize` | `2` | Maximum Rehumanize retries if score is below threshold |

### `styles`

Defines Word formatting for each block type. Each entry supports:

| Key | Description |
|---|---|
| `font` | Font family (e.g. `"Garamond"`) |
| `size_pt` | Font size in points |
| `bold` | `true` / `false` |
| `all_caps` | `true` / `false` |
| `alignment` | `"left"`, `"center"`, `"right"`, `"justify"` |
| `space_before` / `space_after` | Paragraph spacing in points |
| `first_line_cm` | First-line indent in cm |
| `hanging_cm` | Hanging indent in cm (used for headings) |

### `page`

Controls the Word document page dimensions and margins (cm values).

## Formatting Behaviour

The parser converts ChatGPT's markdown output to typed blocks before writing:

| ChatGPT output | Block type | Word style |
|---|---|---|
| `# Chapter X` + title line | `chapter` | Heading 1 |
| `# Chapter X: Title` | `chapter` | Heading 1 |
| `2.1 Section Title` (any heading tag) | `heading2` | Heading 2 |
| `2.1.1 Subsection Title` (any heading tag) | `heading3` | Heading 3 |
| Body paragraph | `body` | Normal |
| `- bullet` / `• bullet` | `list_item` | Normal |
| `Table X`, `Fig. X`, `Placement:`, `Equation` | `artifact` | Normal |

**Section numbers are stripped from headings** — Word's built-in multilevel numbering generates them automatically (1, 1.1, 1.1.1, etc.).

**Heading depth is determined by the section number**, not the HTML tag. `## 2.1.1 Title` becomes Heading 3, and `### 2.1 Title` becomes Heading 2, because the number is the reliable signal.

**Only `body` blocks are sent to StealthWriter.** Headings, tables, figure captions, placement notes, and equations are written to Word as-is.

## Rehumanize Logic

After each StealthWriter pass:

1. The agent reads the human-score shown on the StealthWriter page.
2. If the score is **≥ threshold** (default 70 %) or no score is visible → result is used directly.
3. If the score is **< threshold** → the agent clicks Rehumanize and waits for a new result.
4. This retries up to `max_rehumanize` times (default 2). After that, whatever result was last received is written to Word.

Both values are configurable in `config.json` under `stealthwriter`.

## Files Not Committed

| File / pattern | Reason |
|---|---|
| `.env` | Discord token |
| `browser_state.json` | Live browser session / cookies |
| `browser_profiles/` | Persistent browser profile data |
| `__pycache__/` | Python bytecode |
| `*.docx` | Generated Word documents |
