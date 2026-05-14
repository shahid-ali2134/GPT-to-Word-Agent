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

# Track every image src that has already been successfully downloaded so the
# broader page-wide fallback never returns a figure that was used for a previous
# section (e.g. the old image still visible in ChatGPT's canvas side-panel).
_downloaded_figure_srcs: set[str] = set()


def clear_figure_src_cache() -> None:
    """Clear the set of already-downloaded figure URLs.

    Call once at the start of each chapter's figure resolution pass so the
    exclusion list doesn't grow across chapters.
    """
    global _downloaded_figure_srcs
    _downloaded_figure_srcs.clear()


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

    for origin in (
        "https://chatgpt.com",
        "https://stealthwriter.ai",
        "https://www.stealthwriter.ai",
    ):
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


def _get_last_assistant_text(page: Page) -> str:
    """Return a tail-slice of the last assistant message text for change detection.

    Used alongside message count so that a new response is detected even when
    ChatGPT streams into the same DOM node (count doesn't change) or the count
    lags behind actual rendering.
    """
    try:
        return page.evaluate("""
            () => {
                const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
                if (!msgs.length) return '';
                return (msgs[msgs.length - 1].textContent || '').trim().slice(-120);
            }
        """) or ""
    except Exception:
        return ""


def _wait_for_generation_complete(
    page: Page,
    prev_msg_count: int = 0,
    timeout_sec: int = 600,
    progress=None,
):
    """Poll until ChatGPT stops generating (stop button disappears).

    prev_msg_count — number of assistant messages that existed BEFORE the
    prompt was sent.  We first wait for a new message to appear (guards
    against reading the old response when GPT responds too quickly for the
    stop-button heuristic to catch it), then wait for generation to finish.

    timeout_sec is intentionally generous (default 10 min) because heavy chats
    with long context take significantly longer to generate responses.
    progress — optional callable(str) for status updates every ~30 s.
    """
    stop_selectors = [
        'button[data-testid="stop-button"]',
        'button[aria-label="Stop generating"]',
        'button[aria-label="Stop streaming"]',
    ]
    combined = ", ".join(stop_selectors)

    # ── Phase 1: wait until a NEW assistant message node appears (up to 3 min) ──
    # Heavy/long chats can take 60-120 s before ChatGPT even starts streaming
    # because the model must process the full context before generating the first token.
    P1_TIMEOUT = 180
    p1_start = time.time()
    new_msg_deadline = p1_start + P1_TIMEOUT
    last_p1_reported = 0.0
    while time.time() < new_msg_deadline:
        if _count_assistant_messages(page) > prev_msg_count:
            break
        try:
            if page.query_selector(combined):
                break
        except Exception:
            pass
        now = time.time()
        p1_elapsed = int(now - p1_start)
        if progress and p1_elapsed >= 30 and now - last_p1_reported >= 30:
            progress(
                f"Waiting for ChatGPT to start responding… "
                f"({p1_elapsed}s elapsed, up to {P1_TIMEOUT - p1_elapsed}s remaining)"
            )
            last_p1_reported = now
        page.wait_for_timeout(500)

    # ── Phase 2: wait for the stop button to disappear (generation done) ──────
    phase2_start = time.time()
    deadline = phase2_start + timeout_sec
    last_reported = 0.0
    REPORT_INTERVAL = 30  # seconds between progress messages

    while time.time() < deadline:
        visible = any(
            page.query_selector(s) is not None
            for s in stop_selectors
        )
        if not visible:
            break

        now = time.time()
        elapsed = int(now - phase2_start)
        remaining = int(deadline - now)
        if progress and elapsed >= REPORT_INTERVAL and now - last_reported >= REPORT_INTERVAL:
            progress(
                f"Waiting for ChatGPT to finish… "
                f"({elapsed}s elapsed, up to {remaining}s remaining)"
            )
            last_reported = now

        page.wait_for_timeout(1_000)

    # ── Phase 3: wait for the response text to stabilise ─────────────────────
    # The stop button disappears as soon as ChatGPT finishes *streaming*, but
    # the React DOM may still be patching the last few tokens into the page.
    # Poll the tail of the last response until it stops changing for 2 s so
    # that get_last_response() never reads a partial mid-render snapshot.
    prev_tail = ""
    stable_since = time.time()
    stability_deadline = time.time() + 12  # hard cap: don't block more than 12 s

    while time.time() < stability_deadline:
        curr_tail = _get_last_assistant_text(page)
        if curr_tail != prev_tail:
            prev_tail = curr_tail
            stable_since = time.time()
        elif time.time() - stable_since >= 2.0:
            break  # unchanged for 2 s → DOM fully rendered
        page.wait_for_timeout(400)


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

            // Skip thinking/reasoning collapsible sections (o1 / o3 / o4-mini models).
            // ChatGPT wraps the scratchpad in a <details> element; the summary child
            // shows "Thinking…" and the actual reasoning text is inside — we want none of it.
            if (tag === 'details' || tag === 'summary') return '';
            if (cls.includes('thinking') || cls.includes('reasoning') ||
                cls.includes('chain-of-thought') || cls.includes('scratchpad')) return '';

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
    hydrated it causes the text to be silently discarded and the baseline
    message count to be read incorrectly, causing prompts to fire into a
    half-loaded page.

    Strategy:
      1. Wait for network to go idle (API message-fetch calls complete).
         Capped at 40 s for slow/heavy chats.
      2. Short stability poll: wait until the assistant-message count stops
         changing for 1 s, capped at 5 s total.  This is enough for React to
         finish painting without blocking for the full 30 s that the old
         unbounded poll used to take on 200-message chats.
      3. A small fixed settle (1 s) for any post-render animations.
    """
    # Step 1 — network idle
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_sec * 1_000, 40_000))
    except Exception:
        pass  # timed out — proceed to the stability check

    # Step 2 — short stability poll (max 5 s)
    STABILITY_WINDOW = 1.0   # count must be unchanged for this many seconds
    STABILITY_CAP    = 5.0   # never wait more than this regardless
    prev_count  = -1
    stable_since = time.time()
    cap_deadline = time.time() + STABILITY_CAP

    while time.time() < cap_deadline:
        curr_count = _count_assistant_messages(page)
        if curr_count != prev_count:
            prev_count = curr_count
            stable_since = time.time()
        elif time.time() - stable_since >= STABILITY_WINDOW:
            break  # stable for 1 s → conversation rendered
        page.wait_for_timeout(300)

    # Step 3 — brief final settle
    page.wait_for_timeout(1_000)


def _normalise_url(url: str) -> str:
    """Strip trailing slash, fragment, and query-string for URL comparison."""
    return url.split("?")[0].split("#")[0].rstrip("/")


def navigate_to_chat(chat_url: str, browser_name: str = "chrome") -> str:
    """Navigate to a specific ChatGPT chat URL.

    If the browser is already on the correct page and the input area is
    available, the reload is skipped entirely so a second /writecompletechapter
    call does not disrupt an already-ready session.
    """
    page = _ensure_browser(browser_name)

    # ── Already on the right page? Skip reload if textarea is ready ──────────
    if _normalise_url(page.url or "") == _normalise_url(chat_url):
        el, _ = _find_textarea(page)
        if el:
            return f"Navigated to chat: {chat_url}"

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


def send_message(message: str, allow_retry: bool = True, progress=None) -> str:
    """Type *message* into the current ChatGPT chat and submit it.

    Detects a new response via TWO independent signals: assistant message count
    AND last-message text fingerprint.  A 3-second grace period lets slow DOM
    renders settle before concluding that no response arrived.

    allow_retry — set False for image-generation requests (e.g. "Draw figure X").
    DALL-E generation often starts silently with no immediate text node, so a
    retry would send the same prompt a second time and confuse GPT.  With
    allow_retry=False the function returns a Warning instead of re-sending.

    progress — optional callable(str) forwarded to _wait_for_generation_complete
    so the user sees periodic status updates for long-running generations.
    """
    global _page
    if not _page or _page.is_closed():
        return "Error: browser not open. Call navigate_to_chat first."

    el, _ = _find_textarea(_page)
    if not el:
        return "Error: could not find ChatGPT input area."

    # Snapshot BOTH signals before sending
    msg_count_before = _count_assistant_messages(_page)
    last_text_before = _get_last_assistant_text(_page)

    def _new_response() -> bool:
        return (
            _count_assistant_messages(_page) > msg_count_before
            or _get_last_assistant_text(_page) != last_text_before
        )

    # ── Attempt 1 ────────────────────────────────────────────────────────────
    _type_and_submit(_page, message)
    _page.wait_for_timeout(1_500)
    _wait_for_generation_complete(_page, prev_msg_count=msg_count_before, progress=progress)

    if _new_response():
        return "Message sent; response complete."

    # ── Grace period: DOM may still be settling after generation ─────────────
    _page.wait_for_timeout(3_000)
    if _new_response():
        return "Message sent; response complete."

    if not allow_retry:
        # Don't re-send — caller must decide what to do (e.g. proceed to download)
        return "Warning: Message sent but no immediate response detected (retry suppressed)."

    # ── True retry: re-baseline then send again ───────────────────────────────
    print("  [Browser] No new response detected — retrying send…")
    _wait_for_page_ready(_page, timeout_sec=15)
    msg_count_before = _count_assistant_messages(_page)
    last_text_before = _get_last_assistant_text(_page)
    _type_and_submit(_page, message)
    _page.wait_for_timeout(1_500)
    _wait_for_generation_complete(_page, prev_msg_count=msg_count_before, progress=progress)

    if _new_response():
        return "Message sent; response complete."

    return "Warning: Message sent but no new response detected after retry."


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
    (args) => {
        // args: { baseline, exclude }
        // baseline: index of the first NEW message to scan (messages before this
        //           index existed before the figure request and must be ignored).
        // exclude:  array of src strings already downloaded — never return these
        //           so the canvas panel's lingering old figure is not reused.
        const baseline = (args && args.baseline) || 0;
        const excludeSet = new Set((args && args.exclude) || []);

        const messages = document.querySelectorAll('[data-message-author-role="assistant"]');
        if (!messages.length) return null;

        const validScheme = s => s && !s.endsWith('.svg') && (
            s.startsWith('blob:') ||
            s.startsWith('https://') ||
            s.startsWith('data:image/')
        );

        function largestImg(msg) {
            const imgs = Array.from(msg.querySelectorAll('img[src]')).filter(img => {
                const s = img.src || '';
                if (!validScheme(s)) return false;
                if (excludeSet.has(s)) return false;  // skip already-downloaded
                // naturalWidth works even when the browser window is minimised.
                // getBoundingClientRect is zero when minimised, so use it only as fallback.
                return img.naturalWidth > 0 || img.getBoundingClientRect().width > 0;
            });
            if (!imgs.length) return null;
            imgs.sort((a, b) => {
                const aA = (a.naturalWidth * a.naturalHeight) ||
                           (a.getBoundingClientRect().width * a.getBoundingClientRect().height);
                const bA = (b.naturalWidth * b.naturalHeight) ||
                           (b.getBoundingClientRect().width * b.getBoundingClientRect().height);
                return bA - aA;
            });
            return imgs[0];
        }

        // Scan newest-first, but never go before 'baseline' (messages that existed
        // before this figure was requested) or further back than 5 messages.
        const start = Math.max(baseline, Math.max(0, messages.length - 5));
        for (let j = messages.length - 1; j >= start; j--) {
            const msg = messages[j];

            // Largest rendered img
            const img = largestImg(msg);
            if (img) return { type: 'url', src: img.src };

            // Any valid img URL (even if dimensions are unreadable) → Phase 2
            if (Array.from(msg.querySelectorAll('img[src]')).some(i => {
                const s = i.src || '';
                return validScheme(s) && !excludeSet.has(s);
            }))
                return { type: 'download_btn' };

            // Canvas (Matplotlib)
            const canvas = msg.querySelector('canvas');
            if (canvas && canvas.width > 50 && canvas.height > 50)
                return { type: 'canvas', data: canvas.toDataURL('image/png') };

            // Explicit download button
            for (const el of msg.querySelectorAll('a, button')) {
                if ((el.textContent || '').toLowerCase().includes('download'))
                    return { type: 'download_btn' };
            }
        }

        // ── Broader fallback: canvas panel / side panel ───────────────────────
        // ChatGPT's image canvas feature renders figures in a side panel that
        // is outside [data-message-author-role] containers entirely.
        // Search ALL img elements on the page; the naturalWidth size filter
        // (>= 10 000 px²) reliably excludes icons and UI chrome.
        // Exclude any src already downloaded so old figures in the canvas panel
        // are never returned for a subsequent figure request.
        // Also exclude images inside nav/aside/header (sidebar profile picture)
        // and inside user-message containers (chat header avatar) — these are
        // never generated figures and can be large enough to pass the area filter.
        //
        // IMPORTANT: this scan runs BEFORE the "creating" keyword check so that
        // a completed figure in the canvas panel is detected even when the last
        // assistant message still contains words like "draw / creating / generating"
        // (descriptive text that persists after generation finishes).
        // Old figures are guarded from reuse by excludeSet, not by keyword order.
        const MIN_AREA = 10000;
        const UI_CHROME_TAGS = new Set(['nav', 'aside', 'header', 'footer']);
        function isUiChrome(el) {
            // Exclude images whose alt text marks them as profile/avatar photos
            const alt = (el.getAttribute ? (el.getAttribute('alt') || '') : '').toLowerCase();
            if (alt.includes('profile') || alt.includes('avatar') ||
                alt.includes('your photo') || alt.includes('user photo')) return true;
            let node = el.parentElement;
            while (node) {
                const tag = (node.tagName || '').toLowerCase();
                if (UI_CHROME_TAGS.has(tag)) return true;
                if (node.getAttribute) {
                    if (node.getAttribute('data-message-author-role') === 'user') return true;
                    // Profile / account buttons and containers (ChatGPT uses these for the
                    // user-avatar button in the top-right corner and sidebar).
                    const testid = (node.getAttribute('data-testid') || '').toLowerCase();
                    if (testid.includes('profile') || testid.includes('avatar') ||
                        testid.includes('account') || testid.includes('user-menu')) return true;
                    // Aria-label on nav/profile containers
                    const ariaLabel = (node.getAttribute('aria-label') || '').toLowerCase();
                    if (ariaLabel.includes('profile') || ariaLabel.includes('account') ||
                        ariaLabel.startsWith('your ')) return true;
                    // Explicit navigation role
                    if ((node.getAttribute('role') || '').toLowerCase() === 'navigation') return true;
                }
                node = node.parentElement;
            }
            return false;
        }
        let bestSrc = null, bestArea = 0;
        for (const img of document.querySelectorAll('img[src]')) {
            if (!validScheme(img.src)) continue;
            if (excludeSet.has(img.src)) continue;  // skip already-downloaded
            if (isUiChrome(img)) continue;           // skip avatars / nav images
            const area = img.naturalWidth * img.naturalHeight;
            if (area >= MIN_AREA && area > bestArea) {
                bestArea = area;
                bestSrc = img.src;
            }
        }
        if (bestSrc) return { type: 'url', src: bestSrc };

        // ── "Creating" keyword check — only reached when canvas scan found nothing ──
        // If the last assistant message contains an active-generation keyword,
        // ChatGPT is still drawing the new figure and the canvas panel shows
        // the previous (excluded) figure.  Signal the polling loop to keep waiting.
        {
            const last = messages[messages.length - 1];
            const lastText = (last.textContent || '').toLowerCase();
            const activeKeywords = [
                'analyzing', 'creating', 'generating', 'drawing',
                'working on', 'running', 'producing', 'rendering', 'one last tweak',
                'creating image', 'sketching it out', 'adding final touches',
                'making first draft', 'publishing details'
            ];
            if (activeKeywords.some(kw => lastText.includes(kw)))
                return { type: 'creating' };
        }

        return null;
    }
"""


_MIN_FIGURE_AREA = 10_000  # ~100×100 px — filters out icons / avatars


def screenshot_figure(save_path: str, baseline_msg_count: int = 0) -> bool:
    """Download the most recently generated figure image.

    Works even when the browser window is minimised and produces the original
    image file (no UI chrome, full resolution).

    baseline_msg_count: number of assistant messages that existed BEFORE the
        current figure was requested.  Images in those older messages are
        ignored so the same figure is never returned twice.

    Download order:
      1. page.request.get(src) for HTTPS URLs — uses the browser session/cookies,
         bypasses CORS, gives the original file, works when minimised.
      2. JS fetch for blob: / data: URLs — same-origin, always accessible.
      3. PIL clipboard grab after right-click → Copy image (Windows fallback).
      4. Playwright element.screenshot() — last resort; needs visible window.
    """
    global _page
    if not _page or _page.is_closed():
        return False

    import base64 as _b64
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    # ── Step 1: find the best image src via JS ────────────────────────────────
    # Uses naturalWidth/naturalHeight which are available even when the browser
    # is minimised (unlike getBoundingClientRect which returns zeros).
    # Only scans messages after baseline_msg_count to avoid reusing old figures.
    # Also excludes any src that was already downloaded this chapter.
    img_info = _page.evaluate("""
        (args) => {
            const baseline = (args && args.baseline) || 0;
            const excludeSet = new Set((args && args.exclude) || []);
            const validScheme = s => s && !s.endsWith('.svg') && (
                s.startsWith('blob:') || s.startsWith('https://') || s.startsWith('data:image/')
            );
            const imgArea = img => img.naturalWidth * img.naturalHeight;

            let bestSrc = null, bestArea = 0;

            // Primary: scan new assistant messages only (after baseline)
            const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
            const start = Math.max(baseline, Math.max(0, msgs.length - 5));
            for (let j = msgs.length - 1; j >= start; j--) {
                for (const img of msgs[j].querySelectorAll('img[src]')) {
                    if (!validScheme(img.src)) continue;
                    if (excludeSet.has(img.src)) continue;
                    const area = imgArea(img);
                    if (area > bestArea) { bestArea = area; bestSrc = img.src; }
                }
            }
            if (bestSrc && bestArea >= 10000) return { src: bestSrc, area: bestArea };

            // Fallback: search ALL images on the page so figures displayed in
            // ChatGPT's canvas/side-panel (outside message containers) are found.
            // Exclude already-downloaded srcs so the old canvas image is never reused.
            // Also exclude images inside nav/aside/header (profile avatar) and
            // user-message containers (chat header avatar).
            const UI_CHROME_TAGS = new Set(['nav', 'aside', 'header', 'footer']);
            function isUiChrome(el) {
                // Exclude images whose alt text marks them as profile/avatar photos
                const alt = (el.getAttribute ? (el.getAttribute('alt') || '') : '').toLowerCase();
                if (alt.includes('profile') || alt.includes('avatar') ||
                    alt.includes('your photo') || alt.includes('user photo')) return true;
                let node = el.parentElement;
                while (node) {
                    const tag = (node.tagName || '').toLowerCase();
                    if (UI_CHROME_TAGS.has(tag)) return true;
                    if (node.getAttribute) {
                        if (node.getAttribute('data-message-author-role') === 'user') return true;
                        // Profile / account buttons and containers
                        const testid = (node.getAttribute('data-testid') || '').toLowerCase();
                        if (testid.includes('profile') || testid.includes('avatar') ||
                            testid.includes('account') || testid.includes('user-menu')) return true;
                        // Aria-label on nav/profile containers
                        const ariaLabel = (node.getAttribute('aria-label') || '').toLowerCase();
                        if (ariaLabel.includes('profile') || ariaLabel.includes('account') ||
                            ariaLabel.startsWith('your ')) return true;
                        // Explicit navigation role
                        if ((node.getAttribute('role') || '').toLowerCase() === 'navigation') return true;
                    }
                    node = node.parentElement;
                }
                return false;
            }
            for (const img of document.querySelectorAll('img[src]')) {
                if (!validScheme(img.src)) continue;
                if (excludeSet.has(img.src)) continue;
                if (isUiChrome(img)) continue;
                const area = imgArea(img);
                if (area > bestArea) { bestArea = area; bestSrc = img.src; }
            }
            return (bestSrc && bestArea >= 10000) ? { src: bestSrc, area: bestArea } : null;
        }
    """, {"baseline": baseline_msg_count, "exclude": list(_downloaded_figure_srcs)})

    if img_info:
        src = img_info["src"]
        print(f"  [Browser] screenshot_figure: found image src (area={img_info['area']:.0f}).")

        # ── Approach 1: page.request.get for HTTPS (browser session, no CORS) ─
        if src.startswith("https://"):
            try:
                response = _page.request.get(src)
                if response.ok:
                    with open(save_path, "wb") as f:
                        f.write(response.body())
                    _downloaded_figure_srcs.add(src)
                    print(f"  [Browser] screenshot_figure: saved via HTTPS request.")
                    return True
            except Exception as exc:
                print(f"  [Browser] screenshot_figure HTTPS request failed: {exc}")

        # ── Approach 2: JS fetch for blob:/data: URLs ─────────────────────────
        try:
            data_url = _page.evaluate("""
                async (src) => {
                    if (src.startsWith('data:image')) return src;
                    try {
                        const r = await fetch(src);
                        if (!r.ok) return null;
                        const blob = await r.blob();
                        return new Promise(resolve => {
                            const fr = new FileReader();
                            fr.onloadend = () => resolve(fr.result);
                            fr.readAsDataURL(blob);
                        });
                    } catch (_) { return null; }
                }
            """, src)
            if data_url and isinstance(data_url, str) and "," in data_url:
                _, b64 = data_url.split(",", 1)
                with open(save_path, "wb") as f:
                    f.write(_b64.b64decode(b64))
                _downloaded_figure_srcs.add(src)
                print(f"  [Browser] screenshot_figure: saved via JS fetch.")
                return True
        except Exception as exc:
            print(f"  [Browser] screenshot_figure JS fetch failed: {exc}")

    # ── Approach 3: right-click → Copy image → PIL clipboard (Windows) ────────
    # Tries even when JS couldn't find a usable src (e.g. canvas-rendered images).
    try:
        from PIL import ImageGrab  # type: ignore
        all_msgs = _page.locator('[data-message-author-role="assistant"]')
        msg_count = all_msgs.count()
        best_el = None
        best_area = 0
        for idx in range(msg_count - 1, max(baseline_msg_count - 1, msg_count - 6), -1):
            for k in range(all_msgs.nth(idx).locator("img").count()):
                el = all_msgs.nth(idx).locator("img").nth(k)
                try:
                    box = el.bounding_box()
                    if box and box["width"] * box["height"] > best_area:
                        best_area = box["width"] * box["height"]
                        best_el = el
                except Exception:
                    continue
        if best_el and best_area >= _MIN_FIGURE_AREA:
            best_el.click(button="right")
            _page.wait_for_timeout(600)
            _page.keyboard.press("ArrowDown")
            _page.keyboard.press("ArrowDown")
            _page.keyboard.press("Enter")
            _page.wait_for_timeout(400)
            img = ImageGrab.grabclipboard()
            if img is not None:
                img.save(save_path, "PNG")
                print(f"  [Browser] screenshot_figure: saved via clipboard.")
                return True
            _page.keyboard.press("Escape")
    except Exception as exc:
        print(f"  [Browser] screenshot_figure clipboard copy failed: {exc}")

    # ── Approach 4: Playwright element.screenshot() — last resort ─────────────
    # Needs visible window but captures anything including canvas/WebGL.
    try:
        all_msgs = _page.locator('[data-message-author-role="assistant"]')
        msg_count = all_msgs.count()
        best_el = None
        best_area = 0
        for idx in range(msg_count - 1, max(baseline_msg_count - 1, msg_count - 6), -1):
            for k in range(all_msgs.nth(idx).locator("img").count()):
                el = all_msgs.nth(idx).locator("img").nth(k)
                try:
                    box = el.bounding_box()
                    if box and box["width"] * box["height"] > best_area:
                        best_area = box["width"] * box["height"]
                        best_el = el
                except Exception:
                    continue
        if best_el and best_area >= _MIN_FIGURE_AREA:
            best_el.screenshot(path=save_path)
            print(f"  [Browser] screenshot_figure: saved via element screenshot (area={best_area:.0f}).")
            return True
    except Exception as exc:
        print(f"  [Browser] screenshot_figure element screenshot failed: {exc}")

    print("  [Browser] screenshot_figure: all approaches failed.")
    return False


def get_message_count() -> int:
    """Return the current number of assistant messages visible in the chat.

    Call this BEFORE sending a figure request so that download functions can
    ignore messages that existed before the request and avoid returning a
    figure from a previous generation.
    """
    global _page
    if not _page or _page.is_closed():
        return 0
    try:
        return int(_page.evaluate(
            "() => document.querySelectorAll('[data-message-author-role=\"assistant\"]').length"
        ))
    except Exception:
        return 0


def _try_copy_button(save_path: str) -> bool:
    """Click the 'Copy response' button on the last new assistant message
    and save the image from the Windows clipboard.

    This is the simplest and most reliable approach for canvas/agent mode:
    after generation completes the image is already rendered — no DOM scanning
    needed.  We just click copy and grab whatever landed in the clipboard.

    Returns True if an image was saved, False otherwise.
    """
    global _page
    if not _page or _page.is_closed():
        return False

    import base64 as _b64

    # Small settle — let the action toolbar render after generation ends
    _page.wait_for_timeout(2_000)

    # ── Find and click the Copy-response button ───────────────────────────────
    # ChatGPT renders one "Copy response" action button per assistant message
    # (in the toolbar row: copy, thumbs-up, thumbs-down, ...).  There is exactly
    # one per message, so the LAST matching button on the page belongs to the
    # most recent (figure) message.  We deliberately avoid 'button[aria-label*="copy"]'
    # to skip "Copy code" buttons inside code blocks.
    clicked = _page.evaluate("""
        () => {
            // Most-specific selectors first — these target the per-message copy action,
            // not the "Copy code" buttons inside code blocks.
            const selectors = [
                '[data-testid="copy-turn-action-button"]',
                'button[aria-label="Copy response"]',
                'button[aria-label="Copy message"]',
            ];
            for (const sel of selectors) {
                const all = Array.from(document.querySelectorAll(sel));
                if (all.length) {
                    // Last button = most recent message's copy action
                    all[all.length - 1].click();
                    return sel;  // return selector used (truthy)
                }
            }
            return null;
        }
    """)

    if not clicked:
        print("  [Browser] _try_copy_button: copy button not found.")
        return False

    print("  [Browser] _try_copy_button: copy button clicked, reading clipboard…")
    _page.wait_for_timeout(800)

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    # ── Try 1: PIL clipboard — image data (most common for DALL-E responses) ──
    try:
        from PIL import ImageGrab
        img = ImageGrab.grabclipboard()
        if img is not None:
            img.save(save_path, "PNG")
            _downloaded_figure_srcs.add(f"clipboard:{save_path}")
            print("  [Browser] _try_copy_button: saved via PIL clipboard image.")
            return True
    except Exception as exc:
        print(f"  [Browser] _try_copy_button PIL grab failed: {exc}")

    # ── Try 2: clipboard text might be an image URL ───────────────────────────
    try:
        url = pyperclip.paste()
        if url and url.strip().startswith("https://"):
            url = url.strip()
            response = _page.request.get(url)
            if response.ok:
                with open(save_path, "wb") as f:
                    f.write(response.body())
                _downloaded_figure_srcs.add(url)
                print("  [Browser] _try_copy_button: saved via clipboard URL.")
                return True
    except Exception as exc:
        print(f"  [Browser] _try_copy_button URL approach failed: {exc}")

    # ── Try 3: JS read clipboard API (needs clipboard-read permission) ────────
    try:
        data_url = _page.evaluate("""
            async () => {
                try {
                    const items = await navigator.clipboard.read();
                    for (const item of items) {
                        for (const type of item.types) {
                            if (type.startsWith('image/')) {
                                const blob = await item.getType(type);
                                return new Promise(resolve => {
                                    const fr = new FileReader();
                                    fr.onloadend = () => resolve(fr.result);
                                    fr.readAsDataURL(blob);
                                });
                            }
                        }
                    }
                } catch (_) {}
                return null;
            }
        """)
        if data_url and isinstance(data_url, str) and "," in data_url:
            _, b64 = data_url.split(",", 1)
            with open(save_path, "wb") as f:
                f.write(_b64.b64decode(b64))
            _downloaded_figure_srcs.add(f"clipboard:{save_path}")
            print("  [Browser] _try_copy_button: saved via JS clipboard API.")
            return True
    except Exception as exc:
        print(f"  [Browser] _try_copy_button JS clipboard API failed: {exc}")

    print("  [Browser] _try_copy_button: clipboard was empty or contained no image.")
    return False


def download_last_generated_image(
    save_path: str,
    progress=None,
    interrupt_fn=None,
    baseline_msg_count: int = 0,
) -> bool:
    """
    Download the image from the last ChatGPT assistant message.
    Handles DALL-E (img src), Matplotlib charts (canvas or download-button click).

    Uses a two-tier timeout:
      IDLE_TIMEOUT  — give up if nothing is seen (no image AND no "creating"
                      keyword) for this many seconds in a row.
      MAX_WAIT      — hard cap regardless of how many "creating" signals appear.
    When "Analyzing / Creating / Generating / …" text is detected, the idle
    timer resets so the agent keeps waiting while ChatGPT is actively working.

    progress     — optional callable(str) for periodic status updates.
    interrupt_fn — optional zero-arg callable returning a command string:
                     "skip" → abort the download and return False.
                     "wait" → reset the idle timer and extend the hard deadline
                              by another MAX_WAIT_SEC (user says image is coming).
                   Any other value is ignored.

    Returns True on success, None if the user explicitly skipped.
    """
    global _page
    if not _page or _page.is_closed():
        return False

    import base64 as _b64
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

    # ── Pre-scan: snapshot every currently-visible large image src ───────────
    # Add all large images visible RIGHT NOW (before generation starts) to
    # _downloaded_figure_srcs so the canvas-panel scan never returns a stale
    # figure regardless of how the previous figure was downloaded (copy button,
    # direct URL, download-button click, or Playwright screenshot).
    try:
        pre_srcs = _page.evaluate("""
            () => {
                const MIN = 10000;
                const out = [];
                for (const img of document.querySelectorAll('img[src]')) {
                    const s = img.src || '';
                    if (!s || s.endsWith('.svg')) continue;
                    if (!s.startsWith('blob:') && !s.startsWith('https://') &&
                        !s.startsWith('data:image/')) continue;
                    if (img.naturalWidth * img.naturalHeight >= MIN)
                        out.push(s);
                }
                return out;
            }
        """)
        if pre_srcs:
            for s in pre_srcs:
                _downloaded_figure_srcs.add(s)
            print(f"  [Browser] Pre-scan: excluded {len(pre_srcs)} existing image(s) from future canvas scans.")
    except Exception:
        pass

    # ── Phase 3 helper — element screenshot (works in any ChatGPT mode) ──────
    # Defined early so it can be called both periodically and on timeout.
    # In Agent/o1 mode the JS scanner cannot see the image through evaluate(),
    # but Playwright's element APIs can still take a pixel-perfect screenshot.
    def _try_screenshot() -> bool:
        return screenshot_figure(save_path, baseline_msg_count=baseline_msg_count)

    # ── Poll until image/canvas/download-button appears ───────────────────────
    # Heavy chats make DALL-E take considerably longer — allow up to 10 minutes.
    MAX_WAIT_SEC  = 600   # hard 10-minute cap per "wait" extension
    IDLE_TIMEOUT  = 300   # give up 5 min after the last "creating" signal
    REPORT_INTERVAL = 30  # seconds between progress messages
    # In Agent/o1 mode the JS scanner returns None even when the image is
    # visible; run a Playwright screenshot check every N seconds as a fallback.
    SCREENSHOT_INTERVAL = 60  # seconds between periodic Phase 3 attempts

    result               = None
    start                = time.time()
    deadline             = start + MAX_WAIT_SEC
    last_active          = time.time()
    last_reported        = 0.0
    last_screenshot_try  = start  # don't try immediately — let the image render
    # When the user types "wait", force-keep last_active alive until this time
    # so the idle timer cannot expire while they're telling us to hang on.
    user_wait_until = 0.0

    HINT = "Type **skip** to skip this figure, or **wait** to extend the timeout."

    while time.time() < deadline:
        _page.wait_for_timeout(4_000)

        # ── User interrupt check ──────────────────────────────────────────────
        if interrupt_fn:
            cmd = interrupt_fn().lower().strip()
            if cmd == "skip":
                print("  [Browser] Figure download skipped by user.")
                if progress:
                    progress("Downloading figure… skipped by user.")
                return None  # None = user explicitly skipped (vs False = download failed)
            if cmd == "wait":
                now_cmd = time.time()
                last_active    = now_cmd
                user_wait_until = now_cmd + MAX_WAIT_SEC  # suppress idle for 10 min
                deadline       = now_cmd + MAX_WAIT_SEC   # extend hard cap too
                print("  [Browser] User requested wait — idle timer suspended for 10 min.")
                if progress:
                    progress(
                        f"Downloading figure… got it, waiting up to 10 more min. {HINT}"
                    )

        raw = _page.evaluate(
            _SCAN_FOR_IMAGE_JS,
            {"baseline": baseline_msg_count, "exclude": list(_downloaded_figure_srcs)},
        )
        now = time.time()
        elapsed = int(now - start)

        # If the user said "wait", keep last_active current so idle never fires
        if now < user_wait_until:
            last_active = now

        if raw is None:
            idle_for = int(now - last_active)
            idle_left = IDLE_TIMEOUT - idle_for

            # Periodic Phase 3 check — in Agent/o1 mode the JS scanner never
            # sees the image, but Playwright's element API can screenshot it.
            if now - last_screenshot_try >= SCREENSHOT_INTERVAL:
                last_screenshot_try = now
                print("  [Browser] JS scan empty — trying Phase 3 screenshot check.")
                if _try_screenshot():
                    if progress:
                        progress("Downloading figure… captured via screenshot.")
                    return True

            if idle_for >= IDLE_TIMEOUT:
                print("  [Browser] No image or activity detected — giving up.")
                if progress:
                    progress(
                        f"Downloading figure… no activity for {IDLE_TIMEOUT}s — giving up. {HINT}"
                    )
                break
            print(f"  [Browser] Waiting for image… ({idle_left}s before idle timeout)")
            if progress and now - last_reported >= REPORT_INTERVAL:
                hard_left = int(deadline - now)
                progress(
                    f"Downloading figure… waiting for ChatGPT to generate the image "
                    f"({elapsed}s elapsed, {hard_left}s remaining). {HINT}"
                )
                last_reported = now

        elif raw.get("type") == "creating":
            last_active = time.time()
            print("  [Browser] ChatGPT is still creating the figure, waiting…")
            if progress and now - last_reported >= REPORT_INTERVAL:
                hard_left = int(deadline - now)
                progress(
                    f"Downloading figure… ChatGPT is generating the image "
                    f"({elapsed}s elapsed, up to {hard_left}s remaining). {HINT}"
                )
                last_reported = now

        else:
            result = raw
            break

    if result is None:
        # Poll timed out entirely (Agent/o1 mode: JS scanner saw nothing).
        # Try copy-response button first — image may be rendered in canvas panel
        # even if the JS scanner couldn't see it.
        print("  [Browser] Poll timed out — trying copy-response button.")
        if progress:
            progress("Downloading figure… poll timed out, trying copy-response button.")
        if _try_copy_button(save_path):
            if progress:
                progress("Downloading figure… saved via copy-response clipboard.")
            return True
        # Final fallback: Playwright element screenshot.
        print("  [Browser] Trying final Phase 3 screenshot.")
        if _try_screenshot():
            if progress:
                progress("Downloading figure… captured via screenshot.")
            return True
        return False

    # ── Phase 0: copy-response button (image confirmed ready by polling loop) ──
    # The polling loop just detected the image is rendered — this is the ideal
    # moment to click "Copy response" and read the clipboard.
    print("  [Browser] Image detected — trying copy-response button.")
    if _try_copy_button(save_path):
        # Register the actual image src (not just the clipboard path) so that
        # the next figure's scan never mistakes this figure for the new one.
        if result and result.get('type') == 'url' and result.get('src'):
            _downloaded_figure_srcs.add(result['src'])
        if progress:
            progress("Downloading figure… saved via copy-response clipboard.")
        return True

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
            _downloaded_figure_srcs.add(src)
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
            // Scan last 5 messages newest-first so we find the figure even when
            // a variant-selection or thinking response has pushed it back.
            const start = Math.max(0, messages.length - 5);
            for (let j = messages.length - 1; j >= start; j--) {
                for (const el of messages[j].querySelectorAll('a, button')) {
                    const text = (el.textContent || '').toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    if (text.includes('download') || aria.includes('download')) {
                        el.click();
                        return true;
                    }
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

    # ── Phase 3: Playwright element screenshot ───────────────────────────────
    print("  [Browser] Trying Phase 3: element screenshot fallback.")
    if _try_screenshot():
        return True

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
