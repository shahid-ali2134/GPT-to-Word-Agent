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


def _count_assistant_messages(page: Page) -> int:
    """Return the number of assistant messages currently on the page."""
    try:
        return page.evaluate(
            "() => document.querySelectorAll('[data-message-author-role=\"assistant\"]').length"
        )
    except Exception:
        return 0


def _wait_for_generation_complete(page: Page, prev_msg_count: int = 0, timeout_sec: int = 180):
    """Poll until ChatGPT stops generating (stop button disappears).

    prev_msg_count — number of assistant messages that existed BEFORE the
    prompt was sent.  We first wait for a new message to appear (guards
    against reading the old response when GPT responds too quickly for the
    stop-button heuristic to catch it), then wait for generation to finish.
    """
    stop_selectors = [
        'button[data-testid="stop-button"]',
        'button[aria-label="Stop generating"]',
        'button[aria-label="Stop streaming"]',
    ]
    combined = ", ".join(stop_selectors)

    # ── Phase 1: wait until a NEW assistant message node appears (up to 15 s) ──
    new_msg_deadline = time.time() + 15
    while time.time() < new_msg_deadline:
        if _count_assistant_messages(page) > prev_msg_count:
            break
        try:
            if page.query_selector(combined):
                break
        except Exception:
            pass
        page.wait_for_timeout(500)

    # ── Phase 2: wait for the stop button to disappear (generation done) ──────
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
                // Try multiple selectors — KaTeX versions differ in attribute capitalisation
                const ann = node.querySelector('annotation[encoding="application/x-tex"]')
                         || node.querySelector('annotation[encoding]')
                         || node.querySelector('.katex-mathml annotation')
                         || node.querySelector('math annotation');
                if (ann && ann.textContent.trim())
                    return '\\n\\n$$' + ann.textContent.trim() + '$$\\n\\n';
                // Avoid returning garbled textContent — emit blank lines instead
                return '\\n\\n';
            }
            // KaTeX inline equation
            if (cls.includes('katex') && !cls.includes('katex-html') && !cls.includes('katex-mathml')) {
                const ann = node.querySelector('annotation[encoding="application/x-tex"]')
                         || node.querySelector('annotation[encoding]')
                         || node.querySelector('math annotation');
                if (ann && ann.textContent.trim())
                    return '$$' + ann.textContent.trim() + '$$';
                return '';  // avoid garbled textContent
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

def _wait_for_page_ready(page: Page, timeout_sec: int = 30) -> None:
    """Wait until the ChatGPT SPA has fully hydrated the conversation.

    ChatGPT is a React SPA: after goto() the DOM shell loads quickly
    (domcontentloaded fires) but the conversation history is fetched via API
    and rendered asynchronously.  Typing into the textarea before React has
    hydrated it causes the text to be silently discarded.

    Strategy:
      1. Wait for network to go idle (API calls complete).
      2. Poll until the assistant-message count is stable for 2 s, meaning
         the conversation render is done.
      3. Hard cap of *timeout_sec* seconds so we never block forever.
    """
    # Step 1 — network idle (API responses received)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_sec * 1_000, 20_000))
    except Exception:
        pass  # timeout is fine — we'll still do the stability check

    # Step 2 — wait for rendered message count to stop changing
    deadline = time.time() + timeout_sec
    prev_count = -1
    stable_since = time.time()

    while time.time() < deadline:
        curr_count = _count_assistant_messages(page)
        if curr_count != prev_count:
            prev_count = curr_count
            stable_since = time.time()
        elif time.time() - stable_since >= 2.0:
            break  # stable for 2 s → fully rendered
        page.wait_for_timeout(500)

    # Step 3 — small extra settle for any post-render animations
    page.wait_for_timeout(1_000)


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

    # Wait for the SPA to finish rendering the conversation before returning
    _wait_for_page_ready(page)

    # Verify the page loaded (look for textarea)
    el, _ = _find_textarea(page)
    if not el:
        return f"Warning: navigated to {chat_url} but could not find the input area. Are you logged in?"

    _save_state()
    return f"Navigated to chat: {chat_url}"


_SEND_SELECTORS = [
    'button[data-testid="send-button"]',
    'button[aria-label="Send message"]',
    'button[aria-label="Send prompt"]',
]


def _type_and_submit(page: Page, message: str) -> None:
    """Type *message* into the textarea and click Send (or press Enter)."""
    el, selector = _find_textarea(page)
    if not el:
        return
    _type_text(page, selector, message)

    sent = False
    for sel in _SEND_SELECTORS:
        try:
            btn = page.wait_for_selector(sel, timeout=3_000, state="visible")
            if btn and btn.is_enabled():
                btn.click()
                sent = True
                break
        except Exception:
            continue

    if not sent:
        page.keyboard.press("Enter")


def send_message(message: str) -> str:
    """Type *message* into the current ChatGPT chat and submit it.

    If no new assistant message appears after the first attempt (which can
    happen when the page was still hydrating), the send is automatically
    retried once after a short wait.
    """
    global _page
    if not _page or _page.is_closed():
        return "Error: browser not open. Call navigate_to_chat first."

    el, _ = _find_textarea(_page)
    if not el:
        return "Error: could not find ChatGPT input area."

    msg_count_before = _count_assistant_messages(_page)

    # ── Attempt 1 ────────────────────────────────────────────────────────────
    _type_and_submit(_page, message)
    _page.wait_for_timeout(1_500)
    _wait_for_generation_complete(_page, prev_msg_count=msg_count_before)

    # ── Verify a new response appeared; if not, retry once ───────────────────
    if _count_assistant_messages(_page) <= msg_count_before:
        print("  [Browser] No new response after first send — page may still be loading. Retrying…")
        # Give the page more time to finish hydrating, then try again
        _wait_for_page_ready(_page, timeout_sec=15)
        msg_count_before = _count_assistant_messages(_page)
        _type_and_submit(_page, message)
        _page.wait_for_timeout(1_500)
        _wait_for_generation_complete(_page, prev_msg_count=msg_count_before)

        if _count_assistant_messages(_page) <= msg_count_before:
            return "Warning: Message sent but no new response detected after retry."

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


_SCAN_FOR_IMAGE_JS = """
    () => {
        const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
        if (!messages.length) return null;
        const last = messages[messages.length - 1];

        // Largest loaded img (DALL-E or Matplotlib CDN image)
        const imgs = Array.from(last.querySelectorAll('img[src]')).filter(img => {
            const s = img.src || '';
            return s && !s.endsWith('.svg') && img.naturalWidth > 0 && (
                s.startsWith('blob:') ||
                s.startsWith('https://') ||
                s.startsWith('data:image/')
            );
        });
        imgs.sort((a, b) =>
            (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight)
        );
        if (imgs.length) return { type: 'url', src: imgs[0].src };

        // Canvas element (Matplotlib interactive chart)
        const canvas = last.querySelector('canvas');
        if (canvas && canvas.width > 50 && canvas.height > 50)
            return { type: 'canvas', data: canvas.toDataURL('image/png') };

        // Download link/button visible → image rendered, ready for Phase 2
        for (const el of last.querySelectorAll('a, button')) {
            if ((el.textContent || '').toLowerCase().includes('download'))
                return { type: 'download_btn' };
        }

        // ChatGPT is still actively creating the image — extend the wait
        const text = (last.textContent || '').toLowerCase();
        const activeKeywords = [
            'analyzing', 'creating', 'generating', 'drawing',
            'working on', 'running', 'producing', 'rendering'
        ];
        if (activeKeywords.some(kw => text.includes(kw)))
            return { type: 'creating' };

        return null;
    }
"""


def download_last_generated_image(save_path: str) -> bool:
    """
    Download the image from the last ChatGPT assistant message.
    Handles DALL-E (img src), Matplotlib charts (canvas or download-button click).

    Uses a two-tier timeout:
      IDLE_TIMEOUT  — give up if nothing is seen (no image AND no "creating"
                      keyword) for this many seconds in a row.
      MAX_WAIT      — hard cap regardless of how many "creating" signals appear.
    When "Analyzing / Creating / Generating / …" text is detected, the idle
    timer resets so the agent keeps waiting while ChatGPT is actively working.

    Returns True on success.
    """
    global _page
    if not _page or _page.is_closed():
        return False

    import base64 as _b64
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    # ── Poll until image/canvas/download-button appears ───────────────────────
    MAX_WAIT_SEC  = 300   # hard 5-minute cap
    IDLE_TIMEOUT  = 90    # give up 90 s after the last "creating" signal

    result      = None
    start       = time.time()
    last_active = time.time()  # last time we saw any signal (image OR creating)

    while time.time() - start < MAX_WAIT_SEC:
        _page.wait_for_timeout(4_000)
        raw = _page.evaluate(_SCAN_FOR_IMAGE_JS)

        if raw is None:
            idle_for = int(time.time() - last_active)
            if idle_for >= IDLE_TIMEOUT:
                print("  [Browser] No image or activity detected — giving up.")
                break
            print(f"  [Browser] Waiting for image… ({IDLE_TIMEOUT - idle_for}s idle timeout)")
        elif raw.get("type") == "creating":
            last_active = time.time()
            print("  [Browser] ChatGPT is still creating the figure, waiting…")
        else:
            result = raw
            break

    if result is None:
        return False

    # ── Phase 1: direct download from img src or canvas data URL ─────────────
    try:
        if result.get('type') == 'url':
            src = result['src']
            if src.startswith("blob:"):
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
                """, src)
                _, b64 = data_url.split(",", 1)
                img_bytes = _b64.b64decode(b64)
            else:
                response = _page.request.get(src)
                img_bytes = response.body()
            with open(save_path, "wb") as f:
                f.write(img_bytes)
            return True

        if result.get('type') == 'canvas':
            _, b64 = result['data'].split(",", 1)
            img_bytes = _b64.b64decode(b64)
            with open(save_path, "wb") as f:
                f.write(img_bytes)
            return True

    except Exception as exc:
        print(f"  [Browser] JS image extraction failed: {exc}")

    # ── Phase 2: download button → share modal → click modal's Download button ─
    # DALL-E figures: clicking the figure's download icon opens a share modal
    # (Copy link / X / LinkedIn / Reddit / Download).  The "Download" button
    # in that modal triggers the actual browser file-download.
    _FIND_DOWNLOAD_BTN_JS = """
        () => {
            const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
            if (!messages.length) return false;
            const last = messages[messages.length - 1];
            for (const el of last.querySelectorAll('a, button')) {
                const text = (el.textContent || '').toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                if (text.includes('download') || aria.includes('download')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """
    # JS that clicks the "Download" button INSIDE the share modal
    _CLICK_MODAL_DOWNLOAD_JS = """
        () => {
            // The share modal sits outside the message — search full document
            const all = Array.from(document.querySelectorAll('a, button'));
            for (const el of all) {
                const text = (el.textContent || '').trim().toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                // Must be visible and say exactly "download" (not the in-message btn)
                if ((text === 'download' || aria === 'download') && el.offsetParent !== null) {
                    el.click();
                    return true;
                }
            }
            return false;
        }
    """
    try:
        # Step 1 — click the figure's download icon to open the share modal
        clicked = _page.evaluate(_FIND_DOWNLOAD_BTN_JS)

        if clicked:
            _page.wait_for_timeout(2_000)  # let the share modal render

            # Step 2 — click "Download" in the modal; capture the file download
            try:
                with _page.expect_download(timeout=15_000) as dl_info:
                    modal_clicked = _page.evaluate(_CLICK_MODAL_DOWNLOAD_JS)

                if modal_clicked:
                    download = dl_info.value
                    download.save_as(save_path)
                    _page.keyboard.press("Escape")
                    _page.wait_for_timeout(500)
                    return True
            except Exception as exc:
                print(f"  [Browser] Modal Download button failed: {exc}")

            # Fallback: the modal may contain an <img> we can read directly
            # (used for Matplotlib viewer modals that don't trigger file-download)
            img_src = _page.evaluate("""
                () => {
                    const imgs = Array.from(document.querySelectorAll('img[src]')).filter(img => {
                        const s = img.src || '';
                        return s && !s.endsWith('.svg') && img.naturalWidth > 100 && (
                            s.startsWith('blob:') ||
                            s.startsWith('https://') ||
                            s.startsWith('data:image/')
                        );
                    });
                    imgs.sort((a, b) =>
                        (b.naturalWidth * b.naturalHeight) - (a.naturalWidth * a.naturalHeight)
                    );
                    return imgs.length ? imgs[0].src : null;
                }
            """)

            if img_src:
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
                    img_bytes = _page.request.get(img_src).body()

                with open(save_path, "wb") as f:
                    f.write(img_bytes)
                _page.keyboard.press("Escape")
                _page.wait_for_timeout(500)
                return True

            _page.keyboard.press("Escape")
            _page.wait_for_timeout(500)

    except Exception as exc:
        print(f"  [Browser] Figure download (Phase 2) failed: {exc}")

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
