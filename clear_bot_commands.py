"""
One-shot utility: connect to a Discord bot and wipe all its global slash commands.

Run:  python clear_bot_commands.py
Paste the OLD bot's token when prompted.  The script connects, clears every
global slash command, syncs (so Discord picks up the empty list), then quits.
"""

import asyncio
import sys
import discord


async def clear_all_commands(token: str) -> None:
    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)

    @client.event
    async def on_ready():
        print(f"Connected as: {client.user} (ID: {client.user.id})")
        tree.clear_commands(guild=None)          # wipe every global command
        await tree.sync()                         # push the empty list to Discord
        print("All global slash commands cleared and synced.")
        await client.close()

    try:
        await client.start(token)
    except discord.LoginFailure:
        print("ERROR: Invalid token — double-check and try again.")
        sys.exit(1)


def main():
    token = input("Paste the bot token to clear (PaperDev): ").strip()
    if not token:
        print("No token entered. Exiting.")
        sys.exit(1)
    asyncio.run(clear_all_commands(token))


if __name__ == "__main__":
    main()
