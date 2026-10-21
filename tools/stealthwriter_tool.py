"""
Browser automation for StealthWriter's website UI.

StealthWriter does not expose an official API key in this project, so this
module drives the humanizer page through Playwright in a tab beside ChatGPT.
The first run may require a manual login in the visible browser.
"""

import json
import os
import re
import time

import pyperclip
from playwright.sync_api import Locator, Page, TimeoutError

from tools.browser_tool import open_new_tab, save_browser_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")

_page: Page | None = None
last_humanizations_left: int | None = None  # read from the page before each run


def _load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _stealthwriter_config() -> dict:
    cfg = _load_config()
    return cfg.get("stealthwriter", {})


def _ensure_browser(browser_name: str = "chrome") -> Page:
    global _page

    if _page and not _page.is_closed():
        _page.bring_to_front()
        return _page

    _page = open_new_tab(browser_name)
    # Register scroll-lock init script before any navigation so it executes
    # before StealthWriter's own JS on every page load.
    try:
        _page.add_init_script(_SCROLL_LOCK_INIT_JS)
    except Exception:
        pass
    return _page


def _report(progress, message: str):
    if progress:
        progress(message)


def _visible_count(page: Page, selector: str) -> int:
    try:
        return page.locator(selector).filter(has_not_text=re.compile(r"^\s*$")).count()
    except Exception:
        return 0


def _find_humanizer_input(page: Page, timeout_ms: int = 5_000) -> Locator | None:
    selectors = [
        "textarea",
        '[contenteditable="true"]',
        '[role="textbox"]',
    ]
    # The init-script scroll lock keeps the page pinned at the top, so
    # bounding_box Y values already reflect absolute page position — no
    # manual scroll-to-top needed here.
    try:
        viewport_h = page.evaluate("() => window.innerHeight") or 900
    except Exception:
        viewport_h = 900

    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        candidates = []
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = locator.count()
            except Exception:
                count = 0
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if not candidate.is_enabled():
                        continue
                    box = candidate.bounding_box()
                    if not box:
                        continue
                    if box.get("y", 9999) > viewport_h:
                        continue
                    area = (box.get("width", 0) or 0) * (box.get("height", 0) or 0)
                    if area < 100:
                        continue
                    candidates.append((area, candidate))
                except Exception:
                    continue

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
        page.wait_for_timeout(100)
    return None


def _find_button(page: Page, name: str, timeout_ms: int = 5_000) -> Locator | None:
    pattern = re.compile(name, re.I)
    locators = [
        page.get_by_role("button", name=pattern),
        page.locator("button").filter(has_text=pattern),
        page.locator('[role="button"]').filter(has_text=pattern),
    ]

    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        for locator in locators:
            try:
                count = locator.count()
            except Exception:
                count = 0
            for index in range(count):
                button = locator.nth(index)
                try:
                    if button.is_visible() and button.is_enabled():
                        return button
                except Exception:
                    continue
        page.wait_for_timeout(300)
    return None


def _humanizer_ready(page: Page) -> bool:
    return _find_humanizer_input(page, timeout_ms=1_000) is not None and (
        _find_button(page, r"humanize", timeout_ms=1_000) is not None
        or _visible_count(page, "text=Humanize") > 0
    )


_last_login_alert = 0.0


def _alert_login():
    """Ping the owner on Nexus (user, 2026-10-22: a login wait must never be silent).
    At most one ping per 10 minutes, since callers retry the wait."""
    global _last_login_alert
    if time.time() - _last_login_alert < 600:
        return
    _last_login_alert = time.time()
    try:
        from tools import bookdev
        bookdev.alert("StealthWriter login needed", [
            "The humanizer is waiting for a StealthWriter login in the browser window.",
            "Book work is paused until you log in; it continues by itself afterwards.",
        ])
    except Exception:
        pass


def _wait_for_login_if_needed(page: Page, progress=None):
    sign_in = page.get_by_role("link", name=re.compile(r"sign in|login|log in", re.I))
    try:
        if sign_in.count() and sign_in.first.is_visible():
            sign_in.first.click()
            page.wait_for_load_state("domcontentloaded", timeout=30_000)
    except Exception:
        pass

    if _humanizer_ready(page):
        save_browser_state()
        return

    _report(
        progress,
        "StealthWriter login may be required. Please finish logging in in the browser window.",
    )
    _alert_login()
    deadline = time.time() + 300
    while time.time() < deadline:
        if _humanizer_ready(page):
            _report(progress, "StealthWriter login detected.")
            save_browser_state()
            return
        page.wait_for_timeout(1_000)

    raise TimeoutError("Timed out waiting for StealthWriter login or humanizer controls.")


# Injected via add_init_script() so it runs BEFORE any StealthWriter JS.
# Keeps the page pinned at the top on the humanizer URL only.
_SCROLL_LOCK_INIT_JS = """
(function() {
    var _lock = false;

    function activate() {
        if (_lock) return;
        _lock = true;
        window.scrollTo(0, 0);
        window.addEventListener('scroll', function() {
            if (_lock && window.scrollY > 10) {
                window.scrollTo(0, 0);
            }
        }, {passive: false});
    }

    function checkAndActivate() {
        if (location.href.indexOf('humanizer') !== -1) {
            activate();
        }
    }

    // Run immediately (covers DOMContentLoaded and earlier)
    checkAndActivate();
    // Re-check after DOM is ready in case URL changed during redirect
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', checkAndActivate);
    }
})();
"""


def _js_click(page: Page, locator) -> bool:
    """Click an element via a native JS MouseEvent — no scroll-into-view."""
    try:
        el = locator.element_handle(timeout=2_000)
        if el:
            page.evaluate(
                "(el) => el.dispatchEvent(new MouseEvent('click', "
                "{bubbles: true, cancelable: true, view: window}))",
                el,
            )
            return True
    except Exception:
        pass
    return False


def _navigate_to_humanizer(page: Page, progress=None):
    cfg = _stealthwriter_config()
    base_url = cfg.get("base_url", "https://stealthwriter.ai/")
    humanizer_url = cfg.get("humanizer_url", "https://stealthwriter.ai/")

    current = page.url or ""
    already_on_humanizer = "humanizer" in current

    if already_on_humanizer:
        # Already on the right page — skip both navigations.
        _report(progress, "StealthWriter humanizer already open.")
    elif "stealthwriter.ai" in current:
        # On StealthWriter but wrong page — go directly to humanizer.
        _report(progress, "Opening StealthWriter humanizer page.")
        page.goto(humanizer_url, wait_until="domcontentloaded", timeout=45_000)
        _wait_for_login_if_needed(page, progress)
    else:
        # Fresh start — load base first to handle login, then humanizer.
        _report(progress, "Opening StealthWriter.")
        page.goto(base_url, wait_until="domcontentloaded", timeout=45_000)
        _wait_for_login_if_needed(page, progress)
        _report(progress, "Opening StealthWriter humanizer page.")
        page.goto(humanizer_url, wait_until="domcontentloaded", timeout=45_000)
        _wait_for_login_if_needed(page, progress)

    # After login StealthWriter can redirect to /dashboard, which has no model
    # buttons; make sure we end up on the humanizer itself.
    _ensure_humanizer_url(page, humanizer_url, progress)
    save_browser_state()


def _ensure_humanizer_url(page: Page, humanizer_url: str, progress=None):
    for _ in range(3):
        if "/humanizer" in (page.url or ""):
            return
        _report(progress, f"On {page.url}; opening the humanizer page.")
        page.goto(humanizer_url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(1_500)


class QuotaExhausted(RuntimeError):
    """No StealthWriter humanizations left; retrying cannot help."""


def _reload_humanizer(page: Page, progress=None):
    """Reload the humanizer page so no result from a previous run is left on it
    (a leftover 'Humanize More' panel makes a half-finished new result look done)."""
    cfg = _stealthwriter_config()
    humanizer_url = cfg.get("humanizer_url", "https://stealthwriter.ai/dashboard/humanizer")
    try:
        page.reload(wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        page.goto(humanizer_url, wait_until="domcontentloaded", timeout=45_000)
    _ensure_humanizer_url(page, humanizer_url, progress)
    deadline = time.time() + 30
    while time.time() < deadline and not _humanizer_ready(page):
        page.wait_for_timeout(500)
    _report(progress, "StealthWriter page reloaded.")


def _select_mode(page: Page, mode_name: str, progress=None):
    # A freshly opened page renders the model buttons a moment after the
    # textarea, so retry for a while before giving up.
    deadline = time.time() + 20
    while True:
        try:
            return _select_mode_once(page, mode_name, progress)
        except RuntimeError:
            if time.time() > deadline:
                raise
            cfg = _stealthwriter_config()
            _ensure_humanizer_url(page, cfg.get("humanizer_url", "https://stealthwriter.ai/dashboard/humanizer"), progress)
            page.wait_for_timeout(1_000)


def _select_mode_once(page: Page, mode_name: str, progress=None):
    _report(progress, f"Selecting StealthWriter mode: {mode_name}.")

    # Helper: click without scroll-into-view using force=True (trusted event).
    # Preferred over _js_click because React/Vue components on StealthWriter
    # ignore untrusted JS dispatchEvent clicks.
    def _force_click(locator) -> bool:
        try:
            locator.click(force=True, timeout=1_500)
            return True
        except Exception:
            return False

    # 1. Button-based UI (current StealthWriter design) ─────────────────────
    exact_btn = page.get_by_role("button", name=re.compile(re.escape(mode_name), re.I))
    try:
        if exact_btn.count():
            for i in range(exact_btn.count()):
                btn = exact_btn.nth(i)
                if btn.is_visible():
                    if _force_click(btn):
                        page.wait_for_timeout(300)
                        return
    except Exception:
        pass

    # Also try any visible element whose text content matches the mode name.
    exact_text = page.get_by_text(mode_name, exact=True)
    try:
        if exact_text.count():
            for i in range(exact_text.count()):
                el = exact_text.nth(i)
                if el.is_visible():
                    if _force_click(el):
                        page.wait_for_timeout(300)
                        return
    except Exception:
        pass

    # 2. Dropdown-based UI (legacy) ─────────────────────────────────────────
    selects = page.locator("select")
    for index in range(selects.count()):
        select = selects.nth(index)
        try:
            if not select.is_visible():
                continue
            select.select_option(label=mode_name, timeout=200)
            return
        except Exception:
            continue

    # 3. Dropdown-trigger fallback ───────────────────────────────────────────
    dropdown_triggers = page.locator("button, [role='button']").filter(
        has_text=re.compile(r"ghost|mode|model|mini|pro|legacy", re.I)
    )
    for index in range(dropdown_triggers.count()):
        trigger = dropdown_triggers.nth(index)
        try:
            if not trigger.is_visible() or not trigger.is_enabled():
                continue
            _force_click(trigger)
            page.wait_for_timeout(300)
            option = page.get_by_text(mode_name, exact=True)
            if option.count() and option.first.is_visible():
                if _force_click(option.first):
                    return
        except Exception:
            continue

    raise RuntimeError(f"Could not select StealthWriter mode '{mode_name}'.")


def _paste_text(locator: Locator, page: Page, text: str):
    # Use force=True: trusted Playwright event, no scroll-into-view.
    try:
        locator.click(force=True, timeout=2_000)
    except Exception:
        try:
            locator.focus()
        except Exception:
            pass
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    try:
        try:
            _saved_clip = pyperclip.paste()
        except Exception:
            _saved_clip = None

        pyperclip.copy(text)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(500)

        if _saved_clip is not None:
            try:
                pyperclip.copy(_saved_clip)
            except Exception:
                pass
    except Exception:
        try:
            locator.fill(text)
        except Exception:
            page.keyboard.type(text, delay=1)
        page.wait_for_timeout(500)


def _read_clipboard(page: Page) -> str:
    try:
        text = page.evaluate("navigator.clipboard.readText()")
        if text:
            return text.strip()
    except Exception:
        pass

    try:
        return (pyperclip.paste() or "").strip()
    except Exception:
        return ""


_WORD_RE = re.compile(r"[a-z]{5,}")


def _is_valid_result(text: str, original: str) -> bool:
    """True when *text* is plausibly the humanized version of *original*.

    The humanized result is a rewording of the original, so it shares most of
    the original's content words (nouns / technical terms of length >= 5).
    StealthWriter UI chrome ("Detection Score", "Humanize More", "Looks Human",
    "words", model names, the green/red legend, etc.) shares almost none — this
    guard rejects that chrome so it can never be written to the document.
    """
    # Short inputs (one sentence) give short results: scale the minimums to the
    # input, otherwise a valid result is never accepted and the run times out.
    min_len = min(40, len(original.strip()) // 2)
    if not text or len(text.strip()) < min_len:
        return False

    orig_words = set(_WORD_RE.findall(original.lower()))
    cand_words = set(_WORD_RE.findall(text.lower()))
    if not cand_words:
        return False
    if not orig_words:
        # No content words in the original to compare against — accept on length.
        return len(text.strip()) >= min_len

    overlap = len(orig_words & cand_words)
    ratio = overlap / len(cand_words)
    # Must share a substantial number of the original's content words AND not be
    # dominated by unrelated (UI) vocabulary.
    return overlap >= min(8, max(2, len(orig_words) // 2)) and ratio >= 0.15


def _extract_result_from_page(page: Page, original_text: str) -> str:
    """Return the humanized result text from the page DOM, or '' if not found.

    Collects every substantial text block and scores each by how many of the
    original's content words it contains.  The humanized result (a rewording of
    the input) scores highly; UI chrome scores ~0.  Among blocks that share
    real content with the original, the one with the highest content-word
    density is returned — this favours the clean result over any wrapper element
    that also contains surrounding UI text.
    """
    try:
        candidates = page.evaluate(
            """(originalText) => {
                const orig = (originalText || '').trim();
                const WORD = /[a-z]{5,}/g;
                const origWords = new Set((orig.toLowerCase().match(WORD) || []));
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();

                const seen = new Set();
                const out = [];
                const sel = 'textarea,[contenteditable="true"],[role="textbox"],' +
                            'div,p,span,section,article';
                for (const el of document.querySelectorAll(sel)) {
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden') continue;
                    const t = norm(el.value || el.innerText || el.textContent || '');
                    if (t.length < 40 || seen.has(t)) continue;
                    seen.add(t);
                    // Skip the input echo — an element still holding the original text.
                    if (t.toLowerCase() === orig.toLowerCase()) continue;
                    const words = t.toLowerCase().match(WORD) || [];
                    if (!words.length) continue;
                    const uniq = new Set(words);
                    let hit = 0;
                    for (const w of uniq) if (origWords.has(w)) hit++;
                    const ratio = hit / uniq.size;
                    // Near-identical density (>= 0.92) means an untouched copy of
                    // the original (the input), not a humanized rewrite — skip it.
                    if (ratio >= 0.92) continue;
                    out.push({ text: t, count: hit, ratio: ratio });
                }
                // Highest content-word density first (clean result beats any
                // wrapper diluted with UI text); tiebreak by absolute overlap.
                out.sort((a, b) => (b.ratio - a.ratio) || (b.count - a.count));
                return out.slice(0, 5).map(o => o.text);
            }""",
            original_text,
        )
    except Exception:
        return ""

    for cand in candidates or []:
        if _is_valid_result(cand, original_text):
            return cand
    return ""


def _is_humanizing(page: Page) -> bool:
    """Return True when StealthWriter is actively processing (spinner visible,
    or Humanize button is disabled/loading).  Used to log progress messages."""
    try:
        return page.evaluate("""
            () => {
                // Loading spinner anywhere on the page
                const spinners = document.querySelectorAll(
                    '[class*="spinner" i],[class*="loading" i],[class*="progress" i],' +
                    '[aria-busy="true"],[data-loading="true"]'
                );
                for (const s of spinners) {
                    const st = window.getComputedStyle(s);
                    if (st.display !== 'none' && st.visibility !== 'hidden') return true;
                }
                // Humanize button disabled (StealthWriter disables it while running)
                for (const btn of document.querySelectorAll('button')) {
                    if (/humanize/i.test(btn.textContent) && btn.disabled) return true;
                }
                return false;
            }
        """)
    except Exception:
        return False


def _read_humanizations_left(page: Page) -> "int | None":
    """Return the 'X/150 humanizations left' count shown on the page, or None.

    This counter drops by one the instant a humanization actually starts, so it
    is the most reliable proof that a Humanize click registered and consumed a
    credit — used to retry the click ONLY when no credit was spent.
    """
    try:
        return page.evaluate("""
            () => {
                const t = document.body.innerText || '';
                const m = t.match(/(\\d+)\\s*\\/\\s*\\d+\\s+humanizations?\\s+left/i);
                return m ? parseInt(m[1], 10) : null;
            }
        """)
    except Exception:
        return None


def _result_panel_ready(page: Page) -> bool:
    """True once the Humanized Result panel exists AND humanization is finished.

    StealthWriter only renders the 'Humanize More' button after a humanization
    completes, so its presence is a reliable 'result is ready' signal — much more
    robust than trying to match the interactive-sentence result container.
    """
    if _is_humanizing(page):
        return False
    try:
        return bool(page.evaluate("""
            () => {
                for (const b of document.querySelectorAll('button')) {
                    if (/humanize\\s+more/i.test(b.textContent || '')) return true;
                }
                return false;
            }
        """))
    except Exception:
        return False


def _copy_result_via_button(page: Page, original: str) -> str:
    """Click the result-panel 'Copy' button and return the copied humanized text.

    Uses a clipboard sentinel so we only accept content that the Copy click
    freshly placed on the clipboard (never stale data).  Saves and restores the
    user's clipboard around the operation.  Returns '' if nothing valid landed.
    """
    try:
        saved = pyperclip.paste()
    except Exception:
        saved = None

    sentinel = "__SW_COPY_SENTINEL__"
    try:
        pyperclip.copy(sentinel)
    except Exception:
        pass

    clicked = False
    for get_btn in (
        lambda: page.get_by_role("button", name=re.compile(r"^\s*cop(y|ied)\s*$", re.I)).first,
        lambda: page.locator("button").filter(has_text=re.compile(r"^\s*cop(y|ied)\s*$", re.I)).first,
        lambda: page.locator("button").filter(has_text=re.compile(r"cop(y|ied)", re.I)).first,
    ):
        try:
            get_btn().click(force=True, timeout=2_000)
            clicked = True
            break
        except Exception:
            pass

    copied = ""
    if clicked:
        page.wait_for_timeout(700)
        try:
            copied = (pyperclip.paste() or "").strip()
        except Exception:
            copied = ""

    # Restore the user's clipboard.
    if saved is not None:
        try:
            pyperclip.copy(saved)
        except Exception:
            pass

    if not copied or copied == sentinel or copied == original.strip():
        return ""
    if _is_valid_result(copied, original):
        return copied
    # A one- or two-sentence input can be reworded with almost no shared long
    # words; the Copy button only ever yields the result, so accept on length.
    if len(_WORD_RE.findall(original.lower())) < 12 and len(copied) >= 0.5 * len(original.strip()):
        return copied
    return ""


def _wait_for_result_and_copy(page: Page, original_text: str, timeout_sec: int, progress=None) -> str:
    _report(progress, "Waiting for StealthWriter to finish humanizing.")
    deadline = time.time() + timeout_sec
    last_progress = time.time()
    orig = original_text.strip()

    orig_words = len(orig.split())
    last_candidate = ""

    def _complete(text: str) -> bool:
        # A 'Humanize More' button left over from the previous run makes the
        # panel look ready while the new result is still streaming in, so only
        # accept a result of plausible length that has stopped changing.
        return len(text.split()) >= 0.7 * orig_words

    while time.time() < deadline:
        # Counter StealthWriter's own scroll-to-result JS.
        try:
            page.evaluate("window.scrollTo(0, 0)")
        except Exception:
            pass

        # Only try to extract once the result panel is actually ready (the
        # 'Humanize More' button has appeared and humanization has stopped).
        if _result_panel_ready(page):
            # Primary: the Copy button → clipboard (ground-truth humanized text,
            # works even when the result renders as interactive sentences).
            # Secondary: read the result text straight from the DOM.
            candidate = _copy_result_via_button(page, orig) or _extract_result_from_page(page, original_text)
            if candidate and _complete(candidate):
                if candidate == last_candidate:
                    return candidate
                last_candidate = candidate
                page.wait_for_timeout(2_000)
                continue

        # Report progress every 30 s so the user knows we are still waiting.
        now = time.time()
        if progress and now - last_progress >= 30:
            elapsed = int(now - (deadline - timeout_sec))
            remaining = int(deadline - now)
            still = "still humanizing…" if _is_humanizing(page) else "waiting for result…"
            _report(progress, f"StealthWriter {still} ({elapsed}s elapsed, {remaining}s remaining)")
            last_progress = now

        page.wait_for_timeout(1_000)

    raise TimeoutError("Timed out waiting for StealthWriter humanized result.")


last_human_score: int | None = None
SCORE_DEBUG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "bookdev", "sw_score_debug.txt")


def _dump_score_debug(page: Page):
    """Save the page's text nodes that look like a score, with their neighbours,
    so the score reader can be fixed when StealthWriter changes its layout."""
    try:
        lines = page.evaluate(
            """() => {
                const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                const nodes = []; let n;
                while ((n = w.nextNode())) { const t = n.textContent.trim(); if (t) nodes.push(t); }
                const out = [];
                nodes.forEach((t, i) => {
                    if (/%|score|human|detect|AI/i.test(t) && t.length < 80)
                        out.push(i + ': ' + nodes.slice(Math.max(0, i - 3), i + 4)
                                 .map(x => x.slice(0, 60)).join(' | '));
                });
                return out.slice(0, 80);
            }"""
        )
        os.makedirs(os.path.dirname(SCORE_DEBUG), exist_ok=True)
        with open(SCORE_DEBUG, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n" + "\n".join(lines or []))
    except Exception:
        pass


def _score_is_green(page: Page, score: int) -> bool | None:
    """True if StealthWriter draws the score in green (the user's pass rule),
    False if in another colour, None if the colour cannot be read."""
    try:
        rgb = page.evaluate(
            """(score) => {
                const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let n;
                while ((n = w.nextNode())) {
                    const t = n.textContent.trim();
                    if (t.length > 40 || !(t === String(score)
                            || new RegExp('(^|\\\\D)' + score + '\\\\s*%').test(t))) continue;
                    let el = n.parentElement;
                    for (let k = 0; el && k < 4; k++, el = el.parentElement) {
                        for (const c of [getComputedStyle(el).color,
                                         getComputedStyle(el).backgroundColor,
                                         getComputedStyle(el).stroke]) {
                            const m = (c || '').match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
                            if (!m || (m[4] !== undefined && parseFloat(m[4]) === 0)) continue;
                            const [r, g, b] = [+m[1], +m[2], +m[3]];
                            if (Math.max(r, g, b) - Math.min(r, g, b) > 40) return [r, g, b];
                        }
                    }
                }
                return null;
            }""",
            score,
        )
        if not rgb:
            return None
        r, g, b = rgb
        return g > r + 30 and g > b + 10
    except Exception:
        return None


def _extract_human_score(page: Page) -> int | None:
    """
    Read the human-percentage score shown in StealthWriter's result panel.
    Looks for a bare '%%' text node that has 'human' within a few nodes of it.
    Returns the integer percentage, or None if no score is visible.
    """
    try:
        score = page.evaluate(
            """() => {
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                );
                const nodes = [];
                let n;
                while ((n = walker.nextNode())) {
                    const t = n.textContent.trim();
                    if (t) nodes.push(t);
                }
                // Current layout (2026-10): "96" | "%" | "human" as separate nodes.
                for (let i = 0; i + 2 < nodes.length; i++) {
                    if (/^\\d{1,3}$/.test(nodes[i]) && nodes[i + 1] === '%'
                            && /human/i.test(nodes[i + 2])) {
                        const v = parseInt(nodes[i], 10);
                        if (v <= 100) return v;
                    }
                }
                // Older layouts: "92%" nodes, then "92% Human" / "Human: 92 %".
                for (const re of [/^(\\d{1,3})\\s*%$/, /(\\d{1,3})\\s*%/]) {
                    for (let i = 0; i < nodes.length; i++) {
                        const m = nodes[i].match(re);
                        if (!m || nodes[i].length > 40) continue;
                        const v = parseInt(m[1], 10);
                        if (v > 100) continue;
                        const nearby = nodes.slice(Math.max(0, i - 4), i + 5).join(' ');
                        if (/human/i.test(nearby)) return v;
                    }
                }
                return null;
            }"""
        )
        return score if isinstance(score, int) else None
    except Exception:
        return None


def _click_main_humanize(page: Page) -> bool:
    """Click the MAIN 'Humanize' button EXACTLY once.

    Matches only a button whose text is exactly 'Humanize' — never 'Humanize
    More' (the separate re-run button) — so the initial humanization consumes
    exactly one credit.  Returns True if a click was dispatched.
    """
    # Exact-name candidates first (accessible name == "Humanize", excludes
    # "Humanize More"), then an exact-text locator, then keyboard activation.
    candidates = [
        lambda: page.get_by_role("button", name=re.compile(r"^\s*humanize\s*$", re.I)).first,
        lambda: page.locator("button").filter(
            has_text=re.compile(r"^\s*humanize\s*$", re.I)).first,
    ]
    for get_btn in candidates:
        try:
            get_btn().click(force=True, timeout=2_000)
            return True
        except Exception:
            pass
    # Keyboard fallback on the exact-name button
    try:
        btn = page.get_by_role("button", name=re.compile(r"^\s*humanize\s*$", re.I)).first
        btn.focus(timeout=1_000)
        page.keyboard.press("Enter")
        return True
    except Exception:
        return False


def _try_rehumanize(page: Page, original_text: str, timeout_sec: int, progress=None) -> str | None:
    """Click ONLY the 'Humanize More' button (in the Humanized Result panel) to
    improve a low-scoring result, and return the new result — or None on failure.

    Deliberately targets ONLY 'Humanize More'.  It never touches the main
    'Humanize' button (which starts a fresh humanization and costs a credit) and
    never falls back to the separate 'Rehumanize' button, per the requirement to
    use only 'Humanize More' for re-runs.  If 'Humanize More' cannot be found,
    return None so the current result is kept rather than risk the wrong button.
    """
    try:
        btn = page.get_by_role(
            "button", name=re.compile(r"humanize\s+more", re.I)
        ).first
        if not btn.count():
            # Split button with an icon: fall back to the visible label text.
            btn = page.get_by_text(re.compile(r"^\s*Humanize More\s*$")).first
        btn.click(force=True, timeout=2_000)
        page.wait_for_timeout(1_500)
        return _wait_for_result_and_copy(page, original_text, timeout_sec, progress)
    except Exception:
        return None


SW_DOM_DEBUG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "bookdev", "sw_dom_debug.html")

# JS helpers for the result panel. Sentences are highlighted spans: green = high
# human impact, red = high AI impact. Clicking one opens "Choose alternative"
# with Option 1..3 + Original (each with a coloured dot) and "New alternatives".
_JS_COLOR = """
const rgbOf = (c) => { const m = (c || '').match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/);
    if (!m || (m[4] !== undefined && parseFloat(m[4]) === 0)) return null; return [+m[1], +m[2], +m[3]]; };
const hue = (el) => { for (const c of [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]) {
    const v = rgbOf(c); if (!v) continue; const [r, g, b] = v;
    if (r > g + 40 && r > b + 20) return 'red'; if (g > r + 30 && g > b + 10) return 'green'; }
    return null; };
"""


def _red_sentences(page: Page) -> list[str]:
    """Texts of the result-panel sentences StealthWriter marks red (high AI impact)."""
    return page.evaluate("""() => {""" + _JS_COLOR + """
        const panel = [...document.querySelectorAll('div,section')].find(d =>
            /Humanized Result/.test(d.textContent) && /Click sentences to swap/i.test(d.textContent)
            && d.querySelectorAll('span').length > 0 && d.textContent.length < 60000);
        if (!panel) return [];
        const out = [];
        for (const s of panel.querySelectorAll('span')) {
            const t = s.textContent.trim();
            if (t.length > 25 && s.children.length === 0 && hue(s) === 'red') out.push(t);
        }
        return [...new Set(out)];
    }""") or []


def _pick_green_alternative(page: Page, max_new: int) -> str:
    """In an open 'Choose alternative' dialog, select a green-dot option, asking for
    'New alternatives' at most *max_new* times. Returns 'green', 'kept' or 'none'."""
    for attempt in range(max_new + 1):
        picked = page.evaluate("""() => {""" + _JS_COLOR + """
            const dlg = [...document.querySelectorAll('[role=dialog],div')].find(d =>
                /Choose alternative/.test(d.textContent) && /Option 1/.test(d.textContent)
                && d.textContent.length < 6000);
            if (!dlg) return 'none';
            const labels = [...dlg.querySelectorAll('*')].filter(e =>
                /^Option \\d$/.test(e.textContent.trim()) && e.children.length === 0);
            for (const lab of labels) {
                const row = lab.closest('label,button,[role=radio],li') || lab.parentElement.parentElement;
                const dot = [...(lab.parentElement || row).querySelectorAll('*')].find(x =>
                    x !== lab && x.getBoundingClientRect().width > 0 && x.getBoundingClientRect().width < 14 && hue(x));
                if (dot && hue(dot) === 'green') { row.click(); return 'green'; }
            }
            return 'red';
        }""")
        if picked in ("green", "none"):
            return picked
        if attempt < max_new:
            try:
                page.get_by_role("button", name=re.compile(r"new alternatives", re.I)).first.click(timeout=2_000)
                page.wait_for_timeout(4_000)
            except Exception:
                break
    return "kept"


def sentence_alternatives(sentence: str, new_rounds: int = 0, progress=None) -> dict:
    """Click one sentence in the current Humanized Result panel and read
    StealthWriter's free alternatives for it (text + green/red dot). Asks for
    'New alternatives' up to *new_rounds* times (capped at 2). Picks nothing:
    the caller puts the chosen wording into the blocks file. Costs no credit."""
    page = _ensure_browser()
    new_rounds = max(0, min(int(new_rounds), 2))
    read_js = """() => {""" + _JS_COLOR + """
        const dlg = [...document.querySelectorAll('[role=dialog],div')].find(d =>
            /Choose alternative/.test(d.textContent) && /Option 1/.test(d.textContent)
            && d.textContent.length < 6000);
        if (!dlg) return null;
        const out = [];
        // Label = innermost element whose text is exactly "Option N" / "Original"
        // (it may also hold the coloured dot as a child element).
        const cands = [...dlg.querySelectorAll('*')].filter(e =>
            /^(Option \\d|Original)$/.test(e.textContent.replace(/\\s+/g, ' ').trim()));
        const labels = cands.filter(e => !cands.some(c => c !== e && e.contains(c)));
        if (!labels.length) return {html: dlg.outerHTML.slice(0, 20000)};
        for (const lab of labels) {
            const row = lab.closest('label,button,[role=radio],li') || lab.parentElement.parentElement;
            const dot = [...(lab.parentElement || row).querySelectorAll('*')].find(x =>
                x !== lab && x.getBoundingClientRect().width > 0 && x.getBoundingClientRect().width < 14 && hue(x));
            const lt = lab.textContent.replace(/\\s+/g, ' ').trim();
            let rowEl = row;
            while (rowEl && rowEl.textContent.replace(/\\s+/g, ' ').trim() === lt && rowEl !== dlg)
                rowEl = rowEl.parentElement;  // climb until the row also holds the sentence
            const text = (rowEl || row).textContent.replace(/\\s+/g, ' ').replace(lt, '').trim();
            out.push({label: lt, color: dot ? hue(dot) : (hue(lab) || null), text});
        }
        return out;
    }"""

    def _read(page_):
        res = page_.evaluate(read_js)
        if isinstance(res, dict):  # dialog found but no labels: keep its HTML for diagnosis
            with open(SW_DOM_DEBUG, "w", encoding="utf-8") as f:
                f.write(res.get("html", ""))
            return []
        return res
    found = []
    try:
        # The same words are also in the input box (pasted text): click the sentence
        # span in the Humanized Result panel, i.e. the innermost span holding it.
        key = sentence.strip()[:60]
        spans = page.locator("span").filter(has_text=key)
        target = None
        for i in range(spans.count() - 1, -1, -1):
            s = spans.nth(i)
            try:
                if s.is_visible() and s.locator("span").filter(has_text=key).count() == 0:
                    target = s
                    break
            except Exception:
                continue
        if target is None:
            return {"ok": False, "error": "sentence not found in the Humanized Result panel "
                    "(only the last run's result is on the page)"}
        target.click(timeout=3_000)
        page.wait_for_timeout(1_500)
        opts = _read(page)
        if opts is None:
            with open(SW_DOM_DEBUG, "w", encoding="utf-8") as f:
                f.write(page.content())
            return {"ok": False, "error": "alternative dialog not found; page saved to " + SW_DOM_DEBUG}
        if not opts:
            return {"ok": False, "error": "dialog found but no options read; its HTML saved to "
                    + SW_DOM_DEBUG}
        found.extend(opts)
        for _ in range(new_rounds):
            page.get_by_role("button", name=re.compile(r"new alternatives", re.I)).first.click(timeout=2_000)
            page.wait_for_timeout(4_000)
            found.extend(o for o in (_read(page) or []) if o["label"] != "Original")
        return {"ok": True, "options": found,
                "note": "green = high human impact; pick one and edit the blocks file by hand"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:300], "options": found}
    finally:
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass


def _swap_red_sentences(page: Page, original: str, progress=None, max_new: int = 2,
                        max_sentences: int = 15) -> str | None:
    """User's rule (2026-10-15): fix red sentences one by one with StealthWriter's
    free sentence alternatives instead of another humanization. Each sentence gets
    at most *max_new* 'New alternatives' rounds (no loops). Returns the re-copied
    result text when anything changed, else None."""
    try:
        reds = _red_sentences(page)[:max_sentences]
    except Exception:
        reds = []
    if not reds:
        return None
    _report(progress, f"{len(reds)} red sentence(s): trying StealthWriter's sentence alternatives.")
    swapped = 0
    for sent in reds:
        try:
            page.get_by_text(sent[:60], exact=False).first.click(timeout=2_000)
            page.wait_for_timeout(1_500)
            res = _pick_green_alternative(page, max_new)
            if res == "none":
                with open(SW_DOM_DEBUG, "w", encoding="utf-8") as f:
                    f.write(page.content())
                _report(progress, "Alternative dialog not recognized; page saved for diagnosis.")
                page.keyboard.press("Escape")
                break
            if res == "green":
                swapped += 1
            page.wait_for_timeout(500)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
    _report(progress, f"Sentence alternatives: {swapped} of {len(reds)} red sentence(s) swapped to green.")
    if not swapped:
        return None
    try:
        return _copy_result_via_button(page, original)
    except Exception:
        return None


def _humanize_text_sync(
    text: str,
    browser_name: str = "chrome",
    mode_name: str | None = None,
    progress=None,
) -> str:
    """
    Humanize text through StealthWriter's website UI and return the result.
    If the human score is below the configured threshold, retries up to
    max_rehumanize times before accepting whatever result is available.
    """
    if not text or not text.strip():
        raise ValueError("Text is required for StealthWriter humanization.")

    cfg = _stealthwriter_config()
    mode_name = mode_name or cfg.get("mode", "Ghost 5.2 Pro")
    timeout_sec = int(cfg.get("timeout_sec", 300))
    threshold = int(cfg.get("human_score_threshold", 70))
    max_rehumanize = int(cfg.get("max_rehumanize", 2))

    page = _ensure_browser(browser_name)
    _navigate_to_humanizer(page, progress)
    _reload_humanizer(page, progress)
    left = _read_humanizations_left(page)
    global last_humanizations_left
    last_humanizations_left = left
    if left == 0:
        raise QuotaExhausted("QUOTA: StealthWriter shows 0 humanizations left.")
    _select_mode(page, mode_name, progress)

    input_box = _find_humanizer_input(page, timeout_ms=10_000)
    if not input_box:
        raise RuntimeError("Could not find StealthWriter input text area.")

    _report(progress, "Clipboard in use — hold Ctrl+C for ~2 seconds.")
    _paste_text(input_box, page, text)

    # Give StealthWriter's JS a moment to process the pasted text (word count,
    # button enable state, etc.) before we try to click Humanize.
    page.wait_for_timeout(1_000)

    _report(progress, "Starting StealthWriter humanization.")

    # Press the main "Humanize" button.  A press only counts (consumes a credit)
    # when humanization actually STARTS, which the "X/150 humanizations left"
    # counter reflects immediately.  We therefore retry the click ONLY while we
    # can PROVE no credit was consumed (counter readable and unchanged) — so the
    # button reliably gets pressed without ever double-charging.
    credits_before = _read_humanizations_left(page)

    def _humanization_started() -> bool:
        if credits_before is not None:
            now = _read_humanizations_left(page)
            if now is not None and now < credits_before:
                return True
        return _is_humanizing(page) or _result_panel_ready(page)

    # If the counter is unreadable we cannot verify a credit was NOT spent, so we
    # click only once to avoid any risk of double-charging.  When it is readable,
    # allow a few safe retries.
    max_click_attempts = 4 if credits_before is not None else 1
    started = False

    for attempt in range(max_click_attempts):
        clicked = _click_main_humanize(page)
        if not clicked and attempt == 0:
            _report(progress, "Warning: Humanize button not found — retrying…")

        # Poll up to 7 s for proof the click registered.
        poll_deadline = time.time() + 7
        while time.time() < poll_deadline:
            page.wait_for_timeout(500)
            if _humanization_started():
                started = True
                break
        if started:
            break

        # Not started.  Retry ONLY if the counter proves no credit was consumed.
        if credits_before is None:
            break
        now = _read_humanizations_left(page)
        if now is not None and now < credits_before:
            started = True
            break
        _report(progress, f"Humanize click didn't register — retrying ({attempt + 1}/{max_click_attempts}).")

    if started:
        _report(progress, "Humanization started.")
    else:
        _report(progress, "Proceeding to wait for the humanized result…")

    result = _wait_for_result_and_copy(page, text, timeout_sec, progress)
    accepted = False

    global last_human_score
    last_human_score = None
    for attempt in range(max_rehumanize):
        score = _extract_human_score(page)
        last_human_score = score
        if score is None:
            # Accept, but say so and keep the page's score-like text for diagnosis.
            _report(progress, "Human score could not be read from the page.")
            _dump_score_debug(page)
            accepted = True
            break
        green = _score_is_green(page, score)
        if green or (green is None and score >= threshold):
            _report(progress, f"Human score {score}% accepted "
                              f"({'shown in green' if green else f'threshold {threshold}%'}).")
            accepted = True
            break
        _report(
            progress,
            f"Human score {score}% is below {threshold}%. "
            f"Clicking 'Humanize More' (attempt {attempt + 1}/{max_rehumanize}).",
        )
        new_result = _try_rehumanize(page, text, timeout_sec, progress)
        if new_result:
            result = new_result
        else:
            _report(progress, "'Humanize More' button not found. Checking final score.")
            break

    if not accepted:
        # Final score check after the last rehumanize attempt
        final_score = _extract_human_score(page)
        last_human_score = final_score
        if final_score is not None and not _score_is_green(page, final_score):
            # Keep the humanized text (the original would be pure ChatGPT wording);
            # the low score is reported to the user through the run diagnosis.
            _report(
                progress,
                f"Warning: Human score {final_score}% still not green after "
                f"{max_rehumanize} 'Humanize More' attempt(s); keeping the humanized text.",
            )

    # Free sentence-level fixes for whatever is still marked red.
    # Off by default (user, 2026-10-15): only sentences with wrong symbols or
    # meaning get alternatives, chosen by the writer via sentence_alternatives().
    if cfg.get("swap_red_sentences", False):
        swapped = _swap_red_sentences(page, text, progress,
                                      max_new=int(cfg.get("max_new_alternatives", 2)))
        if swapped:
            result = swapped
            score = _extract_human_score(page)
            if score is not None:
                last_human_score = score

    save_browser_state()
    return result


def humanize_text(
    text: str,
    browser_name: str = "chrome",
    mode_name: str | None = None,
    progress=None,
) -> str:
    """
    Humanize text through StealthWriter in a tab beside the ChatGPT tab.
    """
    return _humanize_text_sync(text, browser_name, mode_name, progress)


def _read_scans_left(page: Page) -> "int | None":
    try:
        return page.evaluate("""
            () => {
                const m = (document.body.innerText || '').match(/(\\d+)\\s*\\/\\s*\\d+\\s+scans?\\s+left/i);
                return m ? parseInt(m[1], 10) : null;
            }
        """)
    except Exception:
        return None


def check_for_ai(text: str, timeout_sec: int = 90, progress=None) -> dict:
    """Paste *text* into the humanizer box and click "Check for AI" (a free scan,
    separate quota from humanizations). Returns {"score": human %, "verdict"}.
    The box is cleared of any previous result first, so run this only after the
    sentence alternatives of the last humanize run are no longer needed."""
    page = _ensure_browser()
    _navigate_to_humanizer(page, progress)
    _reload_humanizer(page, progress)
    box = _find_humanizer_input(page, timeout_ms=10_000)
    if box is None:
        return {"ok": False, "error": "humanizer text box not found"}
    _paste_text(box, page, text)
    before = _read_scans_left(page)
    score_re = re.compile(r"Scanned with\s+V\d+\s+(\d{1,3})\s*%")
    # The panel keeps showing the PREVIOUS scan's score (it survives a reload) and the
    # scan counter drops at the click, before the new result arrives. So wait until the
    # old panel disappears or changes, then until it has been stable for a few seconds.
    old = score_re.search(page.inner_text("body"))
    old_txt = old.group(0) if old else None
    btn = _find_button(page, r"check for ai", timeout_ms=10_000)
    if btn is None:
        return {"ok": False, "error": "'Check for AI' button not found"}
    btn.click()
    t0 = time.time()
    deadline = t0 + timeout_sec
    score = verdict = None
    changed, last, stable_since = old_txt is None, None, None
    while time.time() < deadline:
        page.wait_for_timeout(1_500)
        body = page.inner_text("body")
        m = score_re.search(body)
        cur = m.group(0) if m else None
        if not changed and (cur != old_txt or time.time() - t0 > 40):
            changed = True  # new result shown (or same score twice: give up waiting at 40 s)
        if not changed or cur is None:
            continue
        if cur != last:
            last, stable_since = cur, time.time()
            continue
        left = _read_scans_left(page)
        if time.time() - stable_since >= 4 and (before is None or left is None or left < before):
            score = int(m.group(1))
            verdict = "AI Detected" if re.search(r"AI Detected|Detected as AI", body) else "Looks Human"
            break
    if score is None:
        return {"ok": False, "error": f"no scan result within {timeout_sec}s"}
    _report(progress, f"Check for AI: {score}% human ({verdict})")
    return {"ok": True, "score": score, "verdict": verdict, "words": len(text.split()),
            "scans_left": _read_scans_left(page)}


def open_stealthwriter_for_login(browser_name: str = "chrome", progress=None) -> str:
    """Open the StealthWriter humanizer page and wait for the user to log in.

    Used by the /openstealthwriter recovery command so the user can log back in
    (e.g. after the humanization quota reset) without running a full chapter.
    """
    page = _ensure_browser(browser_name)
    _navigate_to_humanizer(page, progress)
    _report(progress, "StealthWriter humanizer page is open and ready.")
    return "StealthWriter humanizer page is open. Log in if prompted, then you can retry writing."


def close_stealthwriter_browser():
    """Close only the StealthWriter tab."""
    global _page
    try:
        if _page and not _page.is_closed():
            _page.close()
    except Exception:
        pass
    _page = None
