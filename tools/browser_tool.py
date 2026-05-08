"""
Browser automation for ChatGPT using Playwright.

Manages a single persistent browser session so the user stays logged in
between agent turns. Browser state (cookies/localStorage) is saved to
browser_state.json after first login.
"""

import json
import os
import time
import pyperclip
from playwright.sync_api import sync_playwright, Page, BrowserContext

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH  = os.path.join(ROOT, "browser_state.json")

# Module-level singletons — one browser session for the lifetime of the agent
_playwright = None
_context: BrowserContext = None
_page: Page = None


# ──────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────

def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get_opera_path(config: dict) -> str | None:
    raw = (config.get("browser", {})
                 .get("browsers", {})
                 .get("opera", {})
                 .get("executable_path"))
    if raw:
        return raw.replace("{username}", os.environ.get("USERNAME", ""))
    return None


def _ensure_browser(browser_name: str = "chrome") -> Page:
    global _playwright, _context, _page

    if _page and not _page.is_closed():
        return _page

    config = _load_config()

    if _playwright is None:
        _playwright = sync_playwright().start()

    launch_kwargs = {
        "headless": False,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
        ],
    }

    if browser_name == "opera":
        opera_exe = _get_opera_path(config)
        if opera_exe and os.path.exists(opera_exe):
            launch_kwargs["executable_path"] = opera_exe
        else:
            print(f"  [Warning] OperaGX not found at configured path, falling back to Chromium]")

    context_kwargs = {}
    if os.path.exists(STATE_PATH):
        context_kwargs["storage_state"] = STATE_PATH

    browser = _playwright.chromium.launch(**launch_kwargs)
    _context = browser.new_context(**context_kwargs)
    _grant_default_permissions()
    _page = _context.new_page()

    # Hide automation fingerprint
    _page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )

    return _page


def _save_state():
    if _context:
        try:
            _context.storage_state(path=STATE_PATH)
        except Exception:
            pass


def _grant_default_permissions():
    if not _context:
        return

    for origin in ("https://stealthwriter.ai", "https://www.stealthwriter.ai"):
        try:
            _context.grant_permissions(
                ["clipboard-read", "clipboard-write"],
                origin=origin,
            )
        except Exception:
            pass


def _wait_for_login(page: Page):
    """
    If not logged in to ChatGPT, wait for the user to log in manually.
    Detects login by the presence of the prompt textarea.
    """
    page.goto("https://chatgpt.com", wait_until="domcontentloaded", timeout=30_000)
    # Check if we're on a login screen
    try:
        page.wait_for_selector(
            '#prompt-textarea, div[contenteditable="true"]',
            timeout=5_000
        )
        return  # Already logged in
    except Exception:
        pass

    print("\n  [Browser] ChatGPT login page detected.")
    print("  [Browser] Please log in to ChatGPT in the browser window that just opened.")
    print("  [Browser] Waiting for you to finish logging in...")

    # Wait up to 3 minutes for the user to log in
    page.wait_for_selector(
        '#prompt-textarea, div[contenteditable="true"]',
        timeout=180_000
    )
    print("  [Browser] Login detected! Saving browser state...")
    _save_state()


def _find_textarea(page: Page):
    """Return the ChatGPT input element, trying several selectors."""
    selectors = [
        "#prompt-textarea",
        'div[contenteditable="true"][data-id="root"]',
        'div[contenteditable="true"]',
        'textarea[data-id="root"]',
    ]
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=3_000, state="visible")
            if el:
                return el, sel
        except Exception:
            continue
    return None, None


def _type_text(page: Page, selector: str, text: str):
    """
    Fast text entry via clipboard paste (handles long/special-char text).
    Falls back to keyboard.type for environments where clipboard isn't available.
    """
    page.click(selector)
    page.wait_for_timeout(400)
    # Clear existing content
    page.keyboard.press("Control+a")
    page.wait_for_timeout(150)
    page.keyboard.press("Delete")
    page.wait_for_timeout(150)

    try:
        pyperclip.copy(text)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(500)
    except Exception:
        # Fallback: type slowly (works but is slow for long text)
        page.keyboard.type(text, delay=5)
        page.wait_for_timeout(300)


def _wait_for_generation_complete(page: Page, timeout_sec: int = 180):
    """Poll until ChatGPT stops generating (stop button disappears)."""
    stop_selectors = [
        'button[data-testid="stop-button"]',
        'button[aria-label="Stop generating"]',
        'button[aria-label="Stop streaming"]',
    ]
    combined = ", ".join(stop_selectors)

    # Wait for the stop button to appear (generation started)
    try:
        page.wait_for_selector(combined, timeout=8_000, state="visible")
    except Exception:
        pass  # Generation may have been near-instant

    # Wait for the stop button to disappear (generation done)
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        visible = any(
            page.query_selector(s) is not None
            for s in stop_selectors
        )
        if not visible:
            break
        page.wait_for_timeout(1_000)

    # Extra settle time
    page.wait_for_timeout(2_000)


def _extract_last_response(page: Page) -> str:
    """
    Extract the last assistant message from the ChatGPT page as markdown-like text.
    Uses JS to walk the DOM and reconstruct heading/paragraph/list structure.
    """
    js = """
    () => {
        const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
        if (!messages.length) return '';
        const last = messages[messages.length - 1];
        const markdown = last.querySelector('.markdown, .prose, [class*="markdown"]') || last;

        function walk(node) {
            if (node.nodeType === 3) return node.textContent;
            const tag = (node.tagName || '').toLowerCase();
            let out = '';

            if (tag === 'h1') return '# ' + node.textContent.trim() + '\\n\\n';
            if (tag === 'h2') return '## ' + node.textContent.trim() + '\\n\\n';
            if (tag === 'h3') return '### ' + node.textContent.trim() + '\\n\\n';
            if (tag === 'h4') return '#### ' + node.textContent.trim() + '\\n\\n';

            if (tag === 'p') {
                let inner = '';
                node.childNodes.forEach(c => {
                    const ct = (c.tagName || '').toLowerCase();
                    if (ct === 'strong') inner += '**' + c.textContent + '**';
                    else if (ct === 'em')     inner += '*' + c.textContent + '*';
                    else inner += c.textContent;
                });
                return inner.trim() + '\\n\\n';
            }

            if (tag === 'li') return '- ' + node.textContent.trim() + '\\n';
            if (tag === 'ul' || tag === 'ol') {
                let s = '';
                node.childNodes.forEach(c => { s += walk(c); });
                return s + '\\n';
            }
            if (tag === 'br') return '\\n';
            if (tag === 'code' || tag === 'pre') return node.textContent;

            node.childNodes.forEach(c => { out += walk(c); });
            return out;
        }

        return walk(markdown).trim();
    }
    """
    result = page.evaluate(js)
    return result or ""


# ──────────────────────────────────────────────
# Public API (called by agent.py)
# ──────────────────────────────────────────────

def navigate_to_chat(chat_url: str, browser_name: str = "chrome") -> str:
    """Navigate to a specific ChatGPT chat URL."""
    page = _ensure_browser(browser_name)

    # First visit — handle login if needed
    if "chatgpt.com" not in (page.url or ""):
        _wait_for_login(page)

    page.goto(chat_url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(2_000)

    # Verify the page loaded (look for textarea)
    el, _ = _find_textarea(page)
    if not el:
        return f"Warning: navigated to {chat_url} but could not find the input area. Are you logged in?"

    _save_state()
    return f"Navigated to chat: {chat_url}"


def send_message(message: str) -> str:
    """Type *message* into the current ChatGPT chat and submit it."""
    global _page
    if not _page or _page.is_closed():
        return "Error: browser not open. Call navigate_to_chat first."

    el, selector = _find_textarea(_page)
    if not el:
        return "Error: could not find ChatGPT input area."

    _type_text(_page, selector, message)

    # Try clicking the send button
    send_selectors = [
        'button[data-testid="send-button"]',
        'button[aria-label="Send message"]',
        'button[aria-label="Send prompt"]',
    ]
    sent = False
    for sel in send_selectors:
        try:
            btn = _page.wait_for_selector(sel, timeout=3_000, state="visible")
            if btn and btn.is_enabled():
                btn.click()
                sent = True
                break
        except Exception:
            continue

    if not sent:
        _page.keyboard.press("Enter")

    _page.wait_for_timeout(1_500)
    _wait_for_generation_complete(_page)
    return "Message sent; response complete."


def get_last_response() -> str:
    """Return the last assistant message from the current ChatGPT chat."""
    global _page
    if not _page or _page.is_closed():
        return "Error: browser not open."
    _page.wait_for_timeout(500)
    text = _extract_last_response(_page)
    return text if text else "Could not extract response — the page may still be loading."


def open_new_tab(browser_name: str = "chrome") -> Page:
    """
    Open a new tab in the existing browser context.

    The ChatGPT page pointer stays unchanged, so send_message/get_last_response
    continue using the original ChatGPT tab.
    """
    global _context
    _ensure_browser(browser_name)
    _grant_default_permissions()
    page = _context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return page


def save_browser_state():
    """Persist cookies/localStorage for all sites in the current browser context."""
    _save_state()


def close_browser():
    """Save state and close the browser."""
    global _playwright, _context, _page
    _save_state()
    try:
        if _context:
            _context.close()
        if _playwright:
            _playwright.stop()
    except Exception:
        pass
    _playwright = _context = _page = None
