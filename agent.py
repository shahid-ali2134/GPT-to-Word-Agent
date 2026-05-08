"""
ChatGPT to Word Agent - simple CLI entry point.
Run: python agent.py
"""

from agent_core import DEFAULT_PROJECT, humanize_with_stealthwriter, write_complete_chapter
from tools.browser_tool import close_browser
from tools.stealthwriter_tool import close_stealthwriter_browser


def main():
    print()
    print("=" * 56)
    print("  ChatGPT to Word Agent")
    print("=" * 56)
    print("  Commands:")
    print("    /writeCompleteChapter")
    print("    /humanize")
    print("    /close")
    print("=" * 56)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nClosing browser. Goodbye!")
            close_browser()
            close_stealthwriter_browser()
            break

        if not user_input:
            continue

        command, *args = user_input.split()
        command = command.lower()

        if command in ("/close", "quit", "exit", "bye", "q"):
            print("Closing browser. Goodbye!")
            close_browser()
            close_stealthwriter_browser()
            break

        if command == "/humanize":
            project = args[0] if len(args) >= 1 else DEFAULT_PROJECT
            print("Paste text to humanize. Finish with a blank line:")
            lines = []
            while True:
                line = input()
                if not line:
                    break
                lines.append(line)
            text = "\n".join(lines).strip()
            if not text:
                print("Error: text is required.")
                continue

            def progress(message: str):
                print(message)

            try:
                result = humanize_with_stealthwriter(
                    text=text,
                    project_name=project,
                    progress=progress,
                )
            except Exception as exc:
                print(f"Error: {exc}")
                continue

            print()
            print("Humanized text:")
            print(result)
            print()
            continue

        if command != "/writecompletechapter":
            print("Unknown command. Use /writeCompleteChapter or /humanize.")
            continue

        project = args[0] if len(args) >= 1 else DEFAULT_PROJECT
        chapter_number = input("Chapter number: ").strip()
        chapter_outline = input("Paste chapter outline: ").strip()
        if not chapter_number.isdigit():
            print("Error: chapter number must be a whole number.")
            continue

        def progress(message: str):
            print(message)

        try:
            result = write_complete_chapter(
                project_name=project,
                chapter_number=int(chapter_number),
                chapter_outline=chapter_outline,
                progress=progress,
            )
        except Exception as exc:
            print(f"Error: {exc}")
            continue

        print()
        print("Done. Wrote the chapter to Word.")
        print(f"Project: {result['project']}")
        print(f"Chapter: {result['chapter']}")
        print(f"Responses written: {result['written_sections']}")
        print(f"Document: {result['word_file_path']}")
        print()


if __name__ == "__main__":
    main()
