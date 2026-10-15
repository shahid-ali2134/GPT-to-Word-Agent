"""SessionStart hook (.claude/settings.json): tells each new Claude Code session
to watch Book Dev's Discord inbox. The MCP server starts the listener itself."""
import json

MSG = ("BOOK DEV (Discord) is the user's only contact channel. The book-agent MCP server starts "
       "the Discord listener automatically. Before anything else this session: (1) call "
       "bookdev_inbox and answer any unread messages with bookdev_send; (2) arm the Monitor tool "
       "with command 'sh bookdev_watch.sh' (timeout_ms 1800000, description 'BookDev Discord "
       "messages') and re-arm it on every expiry; (3) answer each NEW_MSG via bookdev_send, "
       "not in the terminal.")

print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                         "additionalContext": MSG}}))
