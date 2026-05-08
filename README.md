# GPT-to-Word Agent

GPT-to-Word Agent is a Python automation bot that writes long-form content with ChatGPT, humanizes body text through the StealthWriter website UI, and appends the formatted result to a Word document.

It supports a CLI workflow and Discord slash commands.

## Features

- Opens ChatGPT in a visible Playwright browser session.
- Reuses browser state so ChatGPT and StealthWriter logins can persist.
- Sends chapter or section prompts to ChatGPT.
- Preserves document structure from the original ChatGPT response.
- Sends only body prose to StealthWriter, batching each ChatGPT response into one humanization pass.
- Keeps headings, figure placement notes, tables, and other artifacts out of StealthWriter.
- Writes formatted output to `.docx` using configured Word styles.
- Supports Discord slash commands for chapter writing, section writing, standalone humanization, and closing browser sessions.

## Commands

### CLI

```powershell
python agent.py
```

Available commands:

- `/writeCompleteChapter`
- `/humanize`
- `/close`

### Discord

```powershell
python discord_bot.py
```

Slash commands:

- `/writecompletechapter`
- `/writesections`
- `/humanize`
- `/closebrowser`

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
playwright install chromium
```

2. Create `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=optional_test_server_id
```

3. Create `config.json` from the example:

```powershell
Copy-Item config.example.json config.json
```

4. Edit `config.json`:

- Set `projects.book.chat_url` to your ChatGPT conversation URL.
- Set `projects.book.word_file_path` to your target `.docx` file.
- Adjust browser and style settings if needed.

## Browser Login

The first run opens a visible browser. Log in manually to:

- ChatGPT
- StealthWriter

The bot stores browser cookies/local storage in `browser_state.json`, which is intentionally ignored by git.

StealthWriter clipboard permissions are granted automatically for the automation browser context.

## Formatting Behavior

The agent parses ChatGPT output before humanization:

- `Chapter 6` followed by a title becomes Word `Heading 1`.
- `2.1 Section Title` becomes Word `Heading 2`, with `2.1` stripped.
- `2.1.1 Subsection Title` becomes Word `Heading 3`, with `2.1.1` stripped.
- Body text is sent to StealthWriter.
- Tables, figures, figure-placement notes, equations, and headings are not sent to StealthWriter.

This avoids duplicated Word numbering and keeps document structure stable even when StealthWriter rewrites prose.

## Files Not Committed

The repo intentionally ignores:

- `.env`
- `browser_state.json`
- `browser_profiles/`
- `__pycache__/`
- generated `.docx` files

These files may contain local credentials, browser sessions, or machine-specific paths.
