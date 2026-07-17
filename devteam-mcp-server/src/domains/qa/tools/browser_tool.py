"""Tools de browser (screenshot / accessibility / visual regression) — async, ORM-backed.

O Playwright síncrono (`sync_playwright`) e a comparação Pillow rodam em
`asyncio.to_thread` (não travam o event loop do sidecar); só a persistência
(`await store.save_run`) fica no contexto async. O store é tenant-scoped (dual-db).
"""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Lazy imports — set to None if not installed. Tests patch these at module level.
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageChops = None  # type: ignore[assignment]


_VIEWPORTS: dict[str, tuple[int, int]] = {
    "desktop": (1280, 720),
    "tablet": (768, 1024),
    "mobile": (375, 812),
}

_AXE_TAGS: dict[str, list[str]] = {
    "WCAG2A": ["wcag2a", "wcag21a"],
    "WCAG2AA": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
    "WCAG2AAA": ["wcag2a", "wcag2aa", "wcag2aaa", "wcag21a", "wcag21aa"],
}

_AXE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js"


def _url_slug(url: str) -> str:
    slug = re.sub(r"https?://", "", url)
    slug = re.sub(r"[^\w\-]", "_", slug)
    return slug[:60]


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _screenshot_page_blocking(
    settings: Any,
    *,
    url: str,
    viewport: str,
    selector: str | None,
    output_dir: str | None,
) -> tuple[dict, dict[str, Any] | None]:
    """Corpo bloqueante de screenshot_page. Retorna (resposta, kwargs de persistência|None)."""
    if sync_playwright is None:
        return {
            "error": "playwright_not_installed",
            "details": "run: playwright install",
        }, None

    vp = _VIEWPORTS.get(viewport, _VIEWPORTS["desktop"])
    width, height = vp

    save_dir = Path(output_dir) if output_dir else Path(settings.screenshots_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_timestamp()}_{_url_slug(url)}.png"
    path = str(save_dir / filename)

    try:
        with sync_playwright() as pw:
            browser_type = getattr(pw, settings.default_browser)
            browser = browser_type.launch(headless=settings.headless)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, timeout=settings.browser_timeout)
            if selector:
                elem = page.locator(selector).first
                elem.screenshot(path=path)
            else:
                page.screenshot(path=path, full_page=False)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return {
            "error": "browser_error",
            "details": str(exc),
            "tool": "screenshot_page",
        }, None

    ret = {
        "url": url,
        "viewport": viewport,
        "width": width,
        "height": height,
        "path": path,
        "selector": selector,
    }
    persist = {
        "run_type": "screenshot",
        "status": "passed",
        "summary": {"url": url, "viewport": viewport},
        "details": {"path": path, "selector": selector},
    }
    return ret, persist


async def screenshot_page(
    store: Any,
    settings: Any,
    *,
    url: str,
    viewport: str = "desktop",
    selector: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Tira screenshot de uma página via Playwright."""
    ret, persist = await asyncio.to_thread(
        _screenshot_page_blocking,
        settings,
        url=url,
        viewport=viewport,
        selector=selector,
        output_dir=output_dir,
    )
    if persist is not None:
        ret["run_id"] = await store.save_run(**persist)
    return ret


def _check_accessibility_blocking(
    settings: Any,
    *,
    url: str,
    standard: str,
) -> tuple[dict, dict[str, Any] | None]:
    """Corpo bloqueante de check_accessibility. Retorna (resposta, kwargs de persistência|None)."""
    if sync_playwright is None:
        return {
            "error": "playwright_not_installed",
            "details": "run: playwright install",
        }, None

    tags = _AXE_TAGS.get(standard, _AXE_TAGS["WCAG2AA"])
    axe_run_script = f"axe.run({{runOnly: {{type: 'tag', values: {tags!r}}}}})"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=settings.headless)
            page = browser.new_page()
            page.goto(url, timeout=settings.browser_timeout)
            page.add_script_tag(url=_AXE_CDN)
            results: dict = page.evaluate(axe_run_script)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return {
            "error": "browser_error",
            "details": str(exc),
            "tool": "check_accessibility",
        }, None

    raw_violations: list[dict] = results.get("violations") or []
    raw_passes: list[dict] = results.get("passes") or []
    raw_incomplete: list[dict] = results.get("incomplete") or []

    violations = [
        {
            "id": v.get("id"),
            "impact": v.get("impact"),
            "description": v.get("description"),
            "nodes_count": len(v.get("nodes") or []),
            "help_url": v.get("helpUrl"),
        }
        for v in raw_violations
    ]

    ret = {
        "url": url,
        "standard": standard,
        "violations_count": len(violations),
        "passes_count": len(raw_passes),
        "incomplete_count": len(raw_incomplete),
        "violations": violations,
    }
    persist = {
        "run_type": "accessibility",
        "status": "passed" if not violations else "failed",
        "summary": {
            "violations_count": len(violations),
            "passes_count": len(raw_passes),
        },
        "details": {"violations": violations[:10]},
        "repo_path": url,
    }
    return ret, persist


async def check_accessibility(
    store: Any,
    settings: Any,
    *,
    url: str,
    standard: str = "WCAG2AA",
) -> dict:
    """Verifica acessibilidade via Playwright + axe-core."""
    ret, persist = await asyncio.to_thread(
        _check_accessibility_blocking,
        settings,
        url=url,
        standard=standard,
    )
    if persist is not None:
        ret["run_id"] = await store.save_run(**persist)
    return ret


def _visual_regression_blocking(
    settings: Any,
    *,
    url: str,
    baseline_name: str,
    viewport: str,
    threshold_pct: float,
    update_baseline: bool,
) -> tuple[dict, dict[str, Any] | None]:
    """Corpo bloqueante de visual_regression. Retorna (resposta, kwargs de persistência|None)."""
    if sync_playwright is None:
        return {
            "error": "playwright_not_installed",
            "details": "run: playwright install",
        }, None

    if Image is None or ImageChops is None:
        return {
            "error": "pillow_not_installed",
            "details": "pip install Pillow",
        }, None

    vp = _VIEWPORTS.get(viewport, _VIEWPORTS["desktop"])
    width, height = vp

    screenshots_dir = Path(settings.screenshots_dir)
    baselines_dir = Path(settings.baselines_dir)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = str(screenshots_dir / f"{_timestamp()}_{baseline_name}.png")
    baseline_path = str(baselines_dir / f"{baseline_name}.png")

    # Take screenshot
    try:
        with sync_playwright() as pw:
            browser_type = getattr(pw, settings.default_browser)
            browser = browser_type.launch(headless=settings.headless)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, timeout=settings.browser_timeout)
            page.screenshot(path=screenshot_path, full_page=False)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        return {
            "error": "browser_error",
            "details": str(exc),
            "tool": "visual_regression",
        }, None

    baseline_exists = Path(baseline_path).exists()

    if not baseline_exists or update_baseline:
        shutil.copy2(screenshot_path, baseline_path)
        ret = {
            "url": url,
            "baseline_name": baseline_name,
            "match": True,
            "diff_pct": 0.0,
            "threshold_pct": threshold_pct,
            "screenshot_path": screenshot_path,
            "baseline_path": baseline_path,
            "diff_path": None,
            "action": "baseline_created",
        }
        persist = {
            "run_type": "visual_regression",
            "status": "passed",
            "summary": {"action": "baseline_created", "baseline_name": baseline_name},
            "details": {"baseline_path": baseline_path},
            "repo_path": url,
        }
        return ret, persist

    # Compare with baseline
    try:
        img_current = Image.open(screenshot_path).convert("L")
        img_baseline = Image.open(baseline_path).convert("L")

        # Resize to same dimensions if needed
        if img_current.size != img_baseline.size:
            img_current = img_current.resize(img_baseline.size, Image.Resampling.LANCZOS)

        diff = ImageChops.difference(img_current, img_baseline)
        diff_data = list(diff.getdata())
        total_pixels = len(diff_data)
        changed_pixels = sum(1 for px in diff_data if px > 30)
        diff_pct = (changed_pixels / total_pixels) * 100 if total_pixels > 0 else 0.0
        diff_pct = round(diff_pct, 2)

    except Exception as exc:  # noqa: BLE001
        return {
            "error": "comparison_error",
            "details": str(exc),
            "tool": "visual_regression",
        }, None

    match = diff_pct <= threshold_pct
    diff_path: str | None = None

    if not match:
        diff_path = str(screenshots_dir / f"diff_{_timestamp()}_{baseline_name}.png")
        try:
            diff.save(diff_path)
        except Exception:  # noqa: BLE001
            diff_path = None

    ret = {
        "url": url,
        "baseline_name": baseline_name,
        "match": match,
        "diff_pct": diff_pct,
        "threshold_pct": threshold_pct,
        "screenshot_path": screenshot_path,
        "baseline_path": baseline_path,
        "diff_path": diff_path,
        "action": "compared",
    }
    persist = {
        "run_type": "visual_regression",
        "status": "passed" if match else "failed",
        "summary": {"match": match, "diff_pct": diff_pct, "baseline_name": baseline_name},
        "details": {"diff_path": diff_path},
        "repo_path": url,
    }
    return ret, persist


async def visual_regression(
    store: Any,
    settings: Any,
    *,
    url: str,
    baseline_name: str,
    viewport: str = "desktop",
    threshold_pct: float = 2.0,
    update_baseline: bool = False,
) -> dict:
    """Compara screenshot atual com baseline via Pillow."""
    ret, persist = await asyncio.to_thread(
        _visual_regression_blocking,
        settings,
        url=url,
        baseline_name=baseline_name,
        viewport=viewport,
        threshold_pct=threshold_pct,
        update_baseline=update_baseline,
    )
    if persist is not None:
        ret["run_id"] = await store.save_run(**persist)
    return ret
