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
                    if candidate.is_visible() and candidate.is_enabled():
                        box = candidate.bounding_box() or {}
                        area = (box.get("width", 0) or 0) * (box.get("height", 0) or 0)
                        candidates.append((area, candidate))
                except Exception:
                    continue

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
        page.wait_for_timeout(300)
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
    deadline = time.time() + 300
    while time.time() < deadline:
        if _humanizer_ready(page):
            _report(progress, "StealthWriter login detected.")
            save_browser_state()
            return
        page.wait_for_timeout(1_000)

    raise TimeoutError("Timed out waiting for StealthWriter login or humanizer controls.")


def _navigate_to_humanizer(page: Page, progress=None):
    cfg = _stealthwriter_config()
    base_url = cfg.get("base_url", "https://stealthwriter.ai/")
    humanizer_url = cfg.get("humanizer_url", "https://stealthwriter.ai/")

    _report(progress, "Opening StealthWriter.")
    page.goto(base_url, wait_until="domcontentloaded", timeout=45_000)
    _wait_for_login_if_needed(page, progress)

    _report(progress, "Opening StealthWriter humanizer page.")
    page.goto(humanizer_url, wait_until="domcontentloaded", timeout=45_000)
    _wait_for_login_if_needed(page, progress)
    save_browser_state()


def _select_mode(page: Page, mode_name: str, progress=None):
    _report(progress, f"Selecting StealthWriter mode: {mode_name}.")

    selects = page.locator("select")
    for index in range(selects.count()):
        select = selects.nth(index)
        try:
            select.select_option(label=mode_name, timeout=1_500)
            return
        except Exception:
            continue

    exact_text = page.get_by_text(mode_name, exact=True)
    try:
        if exact_text.count() and exact_text.first.is_visible():
            exact_text.first.click()
            return
    except Exception:
        pass

    dropdown_triggers = page.locator("button, [role='button']").filter(
        has_text=re.compile(r"ghost|mode|model|mini|pro", re.I)
    )
    for index in range(dropdown_triggers.count()):
        trigger = dropdown_triggers.nth(index)
        try:
            if not trigger.is_visible() or not trigger.is_enabled():
                continue
            trigger.click()
            page.wait_for_timeout(500)
            option = page.get_by_text(mode_name, exact=True)
            if option.count() and option.first.is_visible():
                option.first.click()
                return
        except Exception:
            continue

    raise RuntimeError(f"Could not select StealthWriter mode '{mode_name}'.")


def _paste_text(locator: Locator, page: Page, text: str):
    locator.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    try:
        pyperclip.copy(text)
        page.keyboard.press("Control+V")
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


def _extract_result_from_page(page: Page, original_text: str) -> str:
    texts = []
    selectors = [
        "textarea",
        '[contenteditable="true"]',
        '[role="textbox"]',
        '[data-testid*="output" i]',
        '[data-testid*="result" i]',
        '[class*="output" i]',
        '[class*="result" i]',
    ]
    for selector in selectors:
        locator = page.locator(selector)
        try:
            count = locator.count()
        except Exception:
            count = 0
        for index in range(count):
            item = locator.nth(index)
            try:
                if not item.is_visible():
                    continue
                value = item.input_value(timeout=500) if selector == "textarea" else item.inner_text(timeout=500)
                value = (value or "").strip()
                if (
                    value
                    and value != original_text.strip()
                    and len(value) > 20
                    and "Sign In" not in value
                    and "Pricing" not in value
                ):
                    texts.append(value)
            except Exception:
                continue

    if not texts:
        return ""
    texts.sort(key=len, reverse=True)
    return texts[0]


def _wait_for_result_and_copy(page: Page, original_text: str, timeout_sec: int, progress=None) -> str:
    _report(progress, "Waiting for StealthWriter to finish humanizing.")
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        copy_button = _find_button(page, r"copy|copied", timeout_ms=1_000)
        if copy_button:
            before_clipboard = _read_clipboard(page)
            try:
                copy_button.click()
                page.wait_for_timeout(800)
            except Exception:
                pass

            copied = _read_clipboard(page)
            if copied and copied != before_clipboard and copied != original_text.strip():
                return copied
            if copied and copied != original_text.strip() and len(copied) > 20:
                return copied

        result = _extract_result_from_page(page, original_text)
        if result:
            return result
        page.wait_for_timeout(1_000)

    raise TimeoutError("Timed out waiting for StealthWriter humanized result.")


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
                for (let i = 0; i < nodes.length; i++) {
                    const m = nodes[i].match(/^(\\d+)%$/);
                    if (m) {
                        const start = Math.max(0, i - 4);
                        const nearby = nodes.slice(start, i + 5).join(' ');
                        if (/human/i.test(nearby)) {
                            return parseInt(m[1], 10);
                        }
                    }
                }
                return null;
            }"""
        )
        return score if isinstance(score, int) else None
    except Exception:
        return None


def _try_rehumanize(page: Page, original_text: str, timeout_sec: int, progress=None) -> str | None:
    """Click Rehumanize (or Humanize again) and return the new result, or None on failure."""
    btn = _find_button(page, r"rehumanize", timeout_ms=3_000)
    if btn is None:
        btn = _find_button(page, r"^humanize$", timeout_ms=3_000)
    if btn is None:
        return None
    btn.click()
    page.wait_for_timeout(1_500)
    return _wait_for_result_and_copy(page, original_text, timeout_sec, progress)


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
    timeout_sec = int(cfg.get("timeout_sec", 180))
    threshold = int(cfg.get("human_score_threshold", 70))
    max_rehumanize = int(cfg.get("max_rehumanize", 2))

    page = _ensure_browser(browser_name)
    _navigate_to_humanizer(page, progress)
    _select_mode(page, mode_name, progress)

    input_box = _find_humanizer_input(page, timeout_ms=10_000)
    if not input_box:
        raise RuntimeError("Could not find StealthWriter input text area.")

    _report(progress, "Pasting text into StealthWriter.")
    _paste_text(input_box, page, text)

    humanize_button = _find_button(page, r"humanize", timeout_ms=10_000)
    if not humanize_button:
        raise RuntimeError("Could not find the StealthWriter Humanize button.")

    _report(progress, "Starting StealthWriter humanization.")
    humanize_button.click()

    result = _wait_for_result_and_copy(page, text, timeout_sec, progress)
    accepted = False

    for attempt in range(max_rehumanize):
        score = _extract_human_score(page)
        if score is None:
            accepted = True  # score unreadable — accept humanized result
            break
        if score >= threshold:
            _report(progress, f"Human score {score}% meets threshold ({threshold}%).")
            accepted = True
            break
        _report(
            progress,
            f"Human score {score}% is below {threshold}%. "
            f"Rehumanizing (attempt {attempt + 1}/{max_rehumanize}).",
        )
        new_result = _try_rehumanize(page, text, timeout_sec, progress)
        if new_result:
            result = new_result
        else:
            _report(progress, "Rehumanize button not found. Checking final score.")
            break

    if not accepted:
        # Final score check after the last rehumanize attempt
        final_score = _extract_human_score(page)
        if final_score is not None and final_score < threshold:
            _report(
                progress,
                f"Warning: Human score {final_score}% still below {threshold}% after "
                f"{max_rehumanize} attempt(s). Using original text.",
            )
            result = text  # fall back to original — don't write low-score content

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


def close_stealthwriter_browser():
    """Close only the StealthWriter tab."""
    global _page
    try:
        if _page and not _page.is_closed():
            _page.close()
    except Exception:
        pass
    _page = None
