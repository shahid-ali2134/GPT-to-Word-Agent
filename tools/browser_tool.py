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


# Selectors that are ONLY present in an active (logged-in) ChatGPT session
_LOGGED_IN_SELECTORS = [
    '[data-testid="profile-button"]',
    'button[aria-label*="user menu" i]',
    'button[aria-label*="account" i]',
    'nav[aria-label*="history" i]',
    'a[href="/"]>svg',          # sidebar home icon (logged-in layout)
]

# Selectors that appear on the logged-OUT / guest landing page
_LOGIN_PAGE_SELECTORS = [
    'button[data-testid="login-button"]',
    'button[data-testid="sign-in-button"]',
    'a[href*="/auth/login"]',
    'button:has-text("Log in")',
    'button:has-text("Sign in")',
]


def _chatgpt_is_logged_in(page: Page) -> bool:
    """
    Return True only when an active ChatGPT session is detected.

    ChatGPT now shows the chat textarea to guest (logged-out) users, so
    checking for the textarea alone is not sufficient — we must verify that
    session-only elements are present and that no login button is visible.
    """
    # If a login/sign-in button is visible → definitely NOT logged in
    for sel in _LOGIN_PAGE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return False
        except Exception:
            pass

    # If any session-only element is visible → logged in
    for sel in _LOGGED_IN_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True
        except Exception:
            pass

    return False


def _wait_for_login(page: Page):
    """
    Navigate to ChatGPT and wait for the user to log in if necessary.
    Uses session-specific UI elements to distinguish logged-in from guest mode.
    """
    try:
        page.goto("https://chatgpt.com", wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        # Navigation interrupted by OAuth redirect — wait for it to settle
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass

    page.wait_for_timeout(2_000)  # let JS finish rendering

    if _chatgpt_is_logged_in(page):
        return  # Already logged in

    print("\n  [Browser] ChatGPT login required.")
    print("  [Browser] Please log in to ChatGPT in the browser window that just opened.")
    print("  [Browser] Waiting for you to finish logging in (up to 3 minutes)...")

    deadline = time.time() + 180
    while time.time() < deadline:
        page.wait_for_timeout(2_000)
        if _chatgpt_is_logged_in(page):
            print("  [Browser] Login detected! Saving browser state...")
            _save_state()
            return

    raise RuntimeError(
        "Login timeout — no active ChatGPT session detected after 3 minutes. "
        "Please run the command again and log in promptly."
    )


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
            const cls = (typeof node.className === 'string') ? node.className : '';
            let out = '';

            // KaTeX display equation wrapper — extract raw LaTeX from MathML annotation
            if (cls.includes('katex-display')) {
                const ann = node.querySelector('annotation[encoding="application/x-tex"]');
                if (ann) return '\\n\\n$$' + ann.textContent.trim() + '$$\\n\\n';
                return node.textContent;
            }
            // KaTeX inline equation
            if (cls.includes('katex') && !cls.includes('katex-html') && !cls.includes('katex-mathml')) {
                const ann = node.querySelector('annotation[encoding="application/x-tex"]');
                if (ann) return '$$' + ann.textContent.trim() + '$$';
                return node.textContent;
            }
            // Skip already-consumed KaTeX sub-elements
            if (cls.includes('katex-html') || cls.includes('katex-mathml')) return '';

            if (tag === 'h1') { let t=''; node.childNodes.forEach(c=>{t+=walk(c);}); return '# ' + t.trim() + '\\n\\n'; }
            if (tag === 'h2') { let t=''; node.childNodes.forEach(c=>{t+=walk(c);}); return '## ' + t.trim() + '\\n\\n'; }
            if (tag === 'h3') { let t=''; node.childNodes.forEach(c=>{t+=walk(c);}); return '### ' + t.trim() + '\\n\\n'; }
            if (tag === 'h4') { let t=''; node.childNodes.forEach(c=>{t+=walk(c);}); return '#### ' + t.trim() + '\\n\\n'; }

            if (tag === 'p') {
                let inner = '';
                node.childNodes.forEach(c => {
                    const ct = (c.tagName || '').toLowerCase();
                    if (ct === 'strong') inner += '**' + c.textContent + '**';
                    else if (ct === 'em')     inner += '*' + c.textContent + '*';
                    else inner += walk(c);
                });
                return inner.trim() + '\\n\\n';
            }

            if (tag === 'li') {
                let inner = '';
                node.childNodes.forEach(c => { inner += walk(c); });
                return '- ' + inner.trim() + '\\n';
            }
            if (tag === 'ul' || tag === 'ol') {
                let s = '';
                node.childNodes.forEach(c => { s += walk(c); });
                return s + '\\n';
            }
            if (tag === 'br') return '\\n';
            if (tag === 'code' || tag === 'pre') return node.textContent;

            if (tag === 'table') {
                const rows = [];
                node.querySelectorAll('tr').forEach(tr => {
                    const cells = [];
                    tr.querySelectorAll('th, td').forEach(cell => {
                        cells.push(cell.textContent.trim().replace(/\\s+/g, ' '));
                    });
                    if (cells.length) rows.push(cells.join('\\t'));
                });
                return rows.length ? rows.join('\\n') + '\\n\\n' : '';
            }
            if (tag === 'tr' || tag === 'th' || tag === 'td') return '';

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

    try:
        page.goto(chat_url, wait_until="domcontentloaded", timeout=30_000)
    except Exception:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
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


def download_last_generated_image(save_path: str) -> bool:
    """
    Download the image from the last ChatGPT assistant message (DALL-E generated).
    Works with both blob: URLs and regular HTTPS URLs.
    Returns True on success.
    """
    global _page
    if not _page or _page.is_closed():
        return False

    _page.wait_for_timeout(2_000)  # let the image fully render

    img_src = _page.evaluate("""
        () => {
            const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
            if (!messages.length) return null;
            const last = messages[messages.length - 1];
            const img = last.querySelector('img[src]');
            return img ? img.src : null;
        }
    """)

    if not img_src:
        return False

    try:
        import base64 as _b64
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

        if img_src.startswith("blob:"):
            data_url = _page.evaluate("""
                async (url) => {
                    const r = await fetch(url);
                    const blob = await r.blob();
                    return new Promise(resolve => {
                        const fr = new FileReader();
                        fr.onloadend = () => resolve(fr.result);
                        fr.readAsDataURL(blob);
                    });
                }
            """, img_src)
            _, b64 = data_url.split(",", 1)
            img_bytes = _b64.b64decode(b64)
        else:
            response = _page.request.get(img_src)
            img_bytes = response.body()

        with open(save_path, "wb") as f:
            f.write(img_bytes)
        return True
    except Exception as exc:
        print(f"  [Browser] Image download failed: {exc}")
        return False


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
