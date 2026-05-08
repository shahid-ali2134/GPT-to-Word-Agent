"""
ChatGPT to Word Agent - Discord slash-command front end.
Run: python discord_bot.py

Required in .env:
  DISCORD_TOKEN = your bot token

Optional in .env:
  DISCORD_GUILD_ID = sync commands instantly to one server
"""

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor

import discord
from discord import app_commands
from dotenv import load_dotenv

from agent_core import (
    DEFAULT_PROJECT,
    finish_chapter,
    humanize_with_stealthwriter,
    recover_pending,
    write_complete_chapter,
    write_sections,
)
from tools.browser_tool import close_browser
from tools.stealthwriter_tool import close_stealthwriter_browser

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
_raw_guild = os.environ.get("DISCORD_GUILD_ID", "")
GUILD_ID = int(_raw_guild) if _raw_guild.isdigit() else None
DISCORD_MAX = 1900
PROGRESS_MIN_SECONDS = 8

executor = ThreadPoolExecutor(max_workers=1)


def _split(text: str) -> list[str]:
    chunks = []
    while len(text) > DISCORD_MAX:
        cut = text.rfind("\n", 0, DISCORD_MAX)
        if cut == -1:
            cut = DISCORD_MAX
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


class WordAgentBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()


bot = WordAgentBot()


async def _send_followup(interaction: discord.Interaction, text: str):
    for chunk in _split(text):
        await interaction.followup.send(chunk)


def _make_progress_sender(interaction: discord.Interaction, loop: asyncio.AbstractEventLoop):
    last_sent = 0.0
    last_message = ""

    important_prefixes = (
        "Opening ChatGPT",
        "Requesting",
        "Writing",
        "Continuing",
        "Humanizing",
        "Saving",
        "OK:",
        "Warning:",
        "Error:",
    )

    def progress(message: str):
        nonlocal last_sent, last_message
        now = time.monotonic()
        is_important = message.startswith(important_prefixes)
        if not is_important:
            return
        if message == last_message and now - last_sent < 30:
            return
        if now - last_sent < PROGRESS_MIN_SECONDS and not message.startswith(("Error:", "Warning:")):
            return

        last_sent = now
        last_message = message
        asyncio.run_coroutine_threadsafe(_send_followup(interaction, message), loop)

    return progress


@bot.event
async def on_ready():
    print(f"Bot online: {bot.user} (ID: {bot.user.id})")
    if GUILD_ID:
        print(f"  Slash commands synced to guild ID: {GUILD_ID}")
    else:
        print("  Global slash commands synced. Discord may take a while to show them.")


@bot.tree.command(
    name="writecompletechapter",
    description="Write a full chapter from ChatGPT into the Word document.",
)
@app_commands.describe(
    write_chapter_number="Chapter number to write",
    outline_file="Upload a .txt file containing the chapter outline",
    project="Project key from config.json",
)
async def write_complete_chapter_command(
    interaction: discord.Interaction,
    write_chapter_number: int,
    outline_file: discord.Attachment,
    project: str = DEFAULT_PROJECT,
):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()

    try:
        outline_bytes = await outline_file.read()
        chapter_outline = outline_bytes.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        await _send_followup(interaction, "Error: outline_file must be a UTF-8 text file.")
        return

    progress = _make_progress_sender(interaction, loop)

    try:
        result = await loop.run_in_executor(
            executor,
            lambda: write_complete_chapter(
                project_name=project,
                chapter_number=write_chapter_number,
                chapter_outline=chapter_outline,
                progress=progress,
            ),
        )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise

    await _send_followup(
        interaction,
        (
            "Done. Wrote the chapter to Word.\n"
            f"Project: {result['project']}\n"
            f"Chapter: {result['chapter']}\n"
            f"Responses written: {result['written_sections']}\n"
            f"Document: {result['word_file_path']}"
        ),
    )


@bot.tree.command(
    name="writesections",
    description="Write one or more specific sections from an uploaded outline.",
)
@app_commands.describe(
    write_chapter_number="Chapter number these sections belong to",
    sections_file="Upload a .txt file with the section(s) and subsections to write",
    project="Project key from config.json",
)
async def write_sections_command(
    interaction: discord.Interaction,
    write_chapter_number: int,
    sections_file: discord.Attachment,
    project: str = DEFAULT_PROJECT,
):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()

    try:
        outline_bytes = await sections_file.read()
        sections_outline = outline_bytes.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        await _send_followup(interaction, "Error: sections_file must be a UTF-8 text file.")
        return

    progress = _make_progress_sender(interaction, loop)

    try:
        result = await loop.run_in_executor(
            executor,
            lambda: write_sections(
                project_name=project,
                chapter_number=write_chapter_number,
                sections_outline=sections_outline,
                progress=progress,
            ),
        )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise

    await _send_followup(
        interaction,
        (
            "Done. Wrote the requested section material to Word.\n"
            f"Project: {result['project']}\n"
            f"Chapter: {result['chapter']}\n"
            f"Responses written: {result['written_responses']}\n"
            f"Document: {result['word_file_path']}"
        ),
    )


@bot.tree.command(
    name="finishchapter",
    description="Complete an in-progress chapter from where GPT left off.",
)
@app_commands.describe(
    chapter_number="Chapter number (optional, for display only)",
    project="Project key from config.json",
)
async def finish_chapter_command(
    interaction: discord.Interaction,
    chapter_number: int | None = None,
    project: str = DEFAULT_PROJECT,
):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    progress = _make_progress_sender(interaction, loop)

    try:
        result = await loop.run_in_executor(
            executor,
            lambda: finish_chapter(
                project_name=project,
                chapter_number=chapter_number,
                progress=progress,
            ),
        )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise

    chapter_line = f"Chapter: {result['chapter']}\n" if result["chapter"] else ""
    await _send_followup(
        interaction,
        (
            "Done. Finished chapter and wrote to Word.\n"
            f"Project: {result['project']}\n"
            f"{chapter_line}"
            f"Responses written: {result['written_sections']}\n"
            f"Document: {result['word_file_path']}"
        ),
    )


@bot.tree.command(
    name="recover",
    description="Write any content that failed to save last time back to the Word document.",
)
@app_commands.describe(project="Project key from config.json")
async def recover_command(
    interaction: discord.Interaction,
    project: str = DEFAULT_PROJECT,
):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    progress = _make_progress_sender(interaction, loop)

    try:
        result = await loop.run_in_executor(
            executor,
            lambda: recover_pending(project_name=project, progress=progress),
        )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise

    await _send_followup(
        interaction,
        f"{result['message']}\nDocument: {result['word_file_path']}",
    )


@bot.tree.command(name="closebrowser", description="Save state and close browser sessions.")
async def close_browser_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, close_browser)
    await loop.run_in_executor(executor, close_stealthwriter_browser)
    await interaction.followup.send("Browser session closed.")


@bot.tree.command(
    name="humanize",
    description="Humanize uploaded text through StealthWriter.",
)
@app_commands.describe(
    text_file="Upload a .txt file containing the text to humanize",
    project="Project key from config.json",
)
async def humanize_command(
    interaction: discord.Interaction,
    text_file: discord.Attachment,
    project: str = DEFAULT_PROJECT,
):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()

    try:
        text_bytes = await text_file.read()
        text = text_bytes.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        await _send_followup(interaction, "Error: text_file must be a UTF-8 text file.")
        return

    progress = _make_progress_sender(interaction, loop)

    try:
        result = await loop.run_in_executor(
            executor,
            lambda: humanize_with_stealthwriter(
                text=text,
                project_name=project,
                progress=progress,
            ),
        )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise

    await _send_followup(interaction, result)


def main():
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        return
    print("Starting Discord bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
