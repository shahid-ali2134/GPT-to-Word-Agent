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

import discord_bridge
from agent_core import (
    DEFAULT_PROJECT,
    FORMATTING_INSTRUCTIONS,
    configure_figure_input_fn,
    configure_figure_interrupt_fn,
    finish_chapter,
    humanize_with_stealthwriter,
    recover_pending,
    send_formatting_instruction,
    write_complete_chapter,
    write_complete_chapter_v2,
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
        intents.message_content = True  # required to read reply text in on_message
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
        try:
            await interaction.followup.send(chunk)
        except discord.HTTPException as exc:
            if exc.code == 50027:
                # Webhook token expired (interactions are only valid 15 min).
                # Fall back to a plain channel message so nothing is lost.
                try:
                    await interaction.channel.send(chunk)
                except Exception:
                    pass
            else:
                raise


def _make_progress_sender(interaction: discord.Interaction, loop: asyncio.AbstractEventLoop):
    last_sent = 0.0
    last_message = ""

    important_prefixes = (
        "Opening ChatGPT",
        "Requesting",
        "Writing",
        "Continuing",
        "Downloading",
        "Recovering",
        "Humanizing",
        "Saving",
        "Waiting",
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


@bot.event
async def on_message(message: discord.Message):
    """Route any non-bot text message to a waiting agent thread (figure input)."""
    if message.author.bot:
        return
    discord_bridge.deliver(message.channel.id, message.content)


def _make_figure_input_fn(interaction: discord.Interaction, loop: asyncio.AbstractEventLoop):
    """Create a sync callable that sends a Discord followup and waits for a user reply."""
    channel_id = interaction.channel_id

    async def _send(text: str) -> None:
        await _send_followup(interaction, text)

    return discord_bridge.make_input_fn(channel_id, _send, loop, timeout_sec=300.0)


def _make_figure_interrupt_fn(interaction: discord.Interaction):
    """Return a non-blocking callable that polls for 'skip' / 'wait' commands.

    The user can type either word in the Discord channel while the agent is
    waiting for DALL-E to finish:
      • "skip"  → abort the current figure download, move to the next figure.
      • "wait"  → reset the idle timer and extend the hard deadline another 10 min.
    """
    return discord_bridge.make_interrupt_fn(interaction.channel_id)


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
    configure_figure_input_fn(_make_figure_input_fn(interaction, loop))
    configure_figure_interrupt_fn(_make_figure_interrupt_fn(interaction))
    try:
        async with interaction.channel.typing():
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
    finally:
        configure_figure_input_fn(None)
        configure_figure_interrupt_fn(None)

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
    name="writecompletechapterv2",
    description="Write a full chapter (batches Word writes every 3 sections for speed).",
)
@app_commands.describe(
    write_chapter_number="Chapter number to write",
    outline_file="Upload a .txt file containing the chapter outline",
    project="Project key from config.json",
)
async def write_complete_chapter_v2_command(
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
    configure_figure_input_fn(_make_figure_input_fn(interaction, loop))
    configure_figure_interrupt_fn(_make_figure_interrupt_fn(interaction))
    try:
        async with interaction.channel.typing():
            result = await loop.run_in_executor(
                executor,
                lambda: write_complete_chapter_v2(
                    project_name=project,
                    chapter_number=write_chapter_number,
                    chapter_outline=chapter_outline,
                    progress=progress,
                ),
            )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise
    finally:
        configure_figure_input_fn(None)
        configure_figure_interrupt_fn(None)

    await _send_followup(
        interaction,
        (
            "Done. Wrote the chapter to Word (v2 — batched every 3 sections).\n"
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
    configure_figure_input_fn(_make_figure_input_fn(interaction, loop))
    configure_figure_interrupt_fn(_make_figure_interrupt_fn(interaction))
    try:
        async with interaction.channel.typing():
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
    finally:
        configure_figure_input_fn(None)
        configure_figure_interrupt_fn(None)

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
    configure_figure_input_fn(_make_figure_input_fn(interaction, loop))
    configure_figure_interrupt_fn(_make_figure_interrupt_fn(interaction))
    try:
        async with interaction.channel.typing():
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
    finally:
        configure_figure_input_fn(None)
        configure_figure_interrupt_fn(None)

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


_INSTRUCT_CHOICES = [
    app_commands.Choice(name="all — all formatting rules at once (use before starting a chapter)", value="all"),
    app_commands.Choice(name="headings — section/subsection numbering (## X.Y, ### X.Y.Z)", value="headings"),
    app_commands.Choice(name="prose — no bullet lists, full paragraphs", value="prose"),
    app_commands.Choice(name="equations — LaTeX $$...$$ and $...$", value="equations"),
    app_commands.Choice(name="figures — placement lines + sequential figure numbers", value="figures"),
    app_commands.Choice(name="tables — Table N. caption + pipe format", value="tables"),
    app_commands.Choice(name="length — full academic detail, no compression", value="length"),
    app_commands.Choice(name="custom — use the message field only", value="custom"),
]


@bot.tree.command(
    name="instruct",
    description="Send a formatting reminder to ChatGPT (fix headings, equations, figures, etc.).",
)
@app_commands.describe(
    topic="Which formatting rule to remind ChatGPT about",
    message="Extra instruction appended to the preset, or the full text when topic=custom",
    project="Project key from config.json",
)
@app_commands.choices(topic=_INSTRUCT_CHOICES)
async def instruct_command(
    interaction: discord.Interaction,
    topic: app_commands.Choice[str],
    message: str = "",
    project: str = DEFAULT_PROJECT,
):
    await interaction.response.defer(thinking=True)
    loop = asyncio.get_running_loop()
    progress = _make_progress_sender(interaction, loop)

    try:
        result = await loop.run_in_executor(
            executor,
            lambda: send_formatting_instruction(
                topic=topic.value,
                project_name=project,
                custom_message=message,
                progress=progress,
            ),
        )
    except Exception as exc:
        await _send_followup(interaction, f"Error: {exc}")
        raise

    # Show the first 300 chars of GPT's reply so the user knows it was received
    reply_preview = result["gpt_reply"][:300].strip()
    if len(result["gpt_reply"]) > 300:
        reply_preview += "…"

    await _send_followup(
        interaction,
        f"Instruction sent (topic: **{result['topic']}**).\nChatGPT replied: {reply_preview}",
    )


def main():
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set in .env")
        return
    print("Starting Discord bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
