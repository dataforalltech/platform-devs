from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.tools.browser_tool import check_accessibility, screenshot_page, visual_regression


def _make_playwright_mock(page_evaluate_return: dict | None = None):
    """Build a mock that mimics sync_playwright context manager."""
    page = MagicMock()
    page.evaluate.return_value = page_evaluate_return or {
        "violations": [],
        "passes": [{"id": "html-has-lang"}],
        "incomplete": [],
    }
    page.locator.return_value.first = MagicMock()
    page.locator.return_value.first.screenshot = MagicMock()
    page.screenshot = MagicMock()

    browser = MagicMock()
    browser.new_page.return_value = page

    browser_type = MagicMock()
    browser_type.launch.return_value = browser

    pw_ctx = MagicMock()
    pw_ctx.chromium = browser_type
    pw_ctx.firefox = browser_type
    pw_ctx.webkit = browser_type

    sync_pw_cm = MagicMock()
    sync_pw_cm.__enter__ = MagicMock(return_value=pw_ctx)
    sync_pw_cm.__exit__ = MagicMock(return_value=False)

    return sync_pw_cm, page


def test_screenshot_page_desktop(store, settings, tmp_path):
    sync_pw_cm, page = _make_playwright_mock()
    settings = settings.model_copy(update={"screenshots_dir": str(tmp_path)})
    with patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm):
        result = screenshot_page(store, settings, url="http://example.com")
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["viewport"] == "desktop"
    assert "path" in result
    assert result["selector"] is None
    assert "run_id" in result


def test_screenshot_page_mobile(store, settings, tmp_path):
    sync_pw_cm, page = _make_playwright_mock()
    settings = settings.model_copy(update={"screenshots_dir": str(tmp_path)})
    with patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm):
        result = screenshot_page(store, settings, url="http://example.com", viewport="mobile")
    assert result["width"] == 375
    assert result["height"] == 812
    assert result["viewport"] == "mobile"


def test_screenshot_page_with_selector(store, settings, tmp_path):
    sync_pw_cm, page = _make_playwright_mock()
    settings = settings.model_copy(update={"screenshots_dir": str(tmp_path)})
    with patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm):
        result = screenshot_page(
            store, settings, url="http://example.com", selector="nav.header"
        )
    assert result["selector"] == "nav.header"
    # element screenshot should be called
    page.locator.assert_called_once_with("nav.header")


def test_screenshot_playwright_not_installed(store, settings, tmp_path):
    settings = settings.model_copy(update={"screenshots_dir": str(tmp_path)})
    with patch("src.tools.browser_tool.sync_playwright", None):
        result = screenshot_page(store, settings, url="http://example.com")
    assert result["error"] == "playwright_not_installed"
    assert "playwright install" in result["details"]


def test_check_accessibility_no_violations(store, settings):
    sync_pw_cm, page = _make_playwright_mock(
        page_evaluate_return={
            "violations": [],
            "passes": [{"id": "html-has-lang"}, {"id": "button-name"}],
            "incomplete": [],
        }
    )
    with patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm):
        result = check_accessibility(store, settings, url="http://example.com")
    assert result["violations_count"] == 0
    assert result["passes_count"] == 2
    assert result["violations"] == []
    assert "run_id" in result


def test_check_accessibility_with_violations(store, settings):
    sync_pw_cm, page = _make_playwright_mock(
        page_evaluate_return={
            "violations": [
                {
                    "id": "color-contrast",
                    "impact": "serious",
                    "description": "Insufficient color contrast",
                    "nodes": [{"html": "<p>text</p>"}, {"html": "<span>more</span>"}],
                    "helpUrl": "https://dequeuniversity.com/rules/axe/4.9/color-contrast",
                }
            ],
            "passes": [{"id": "html-has-lang"}],
            "incomplete": [{"id": "label"}],
        }
    )
    with patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm):
        result = check_accessibility(store, settings, url="http://example.com")
    assert result["violations_count"] == 1
    assert result["incomplete_count"] == 1
    assert result["violations"][0]["id"] == "color-contrast"
    assert result["violations"][0]["nodes_count"] == 2
    assert result["violations"][0]["impact"] == "serious"


def test_visual_regression_baseline_created(store, settings, tmp_path):
    sync_pw_cm, page = _make_playwright_mock()
    settings = settings.model_copy(
        update={
            "screenshots_dir": str(tmp_path / "screenshots"),
            "baselines_dir": str(tmp_path / "baselines"),
        }
    )

    def fake_screenshot(path=None, full_page=False):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"PNG_DATA")

    # Get the page mock and set screenshot side effect
    page.screenshot.side_effect = fake_screenshot

    with patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm):
        result = visual_regression(
            store, settings, url="http://example.com", baseline_name="homepage"
        )
    assert result["action"] == "baseline_created"
    assert result["match"] is True
    assert "run_id" in result


def test_visual_regression_match(store, settings, tmp_path):
    """Pillow mock: diff_pct=0.1, match=True."""
    sync_pw_cm, page = _make_playwright_mock()
    settings = settings.model_copy(
        update={
            "screenshots_dir": str(tmp_path / "screenshots"),
            "baselines_dir": str(tmp_path / "baselines"),
        }
    )

    screenshots_dir = Path(settings.screenshots_dir)
    baselines_dir = Path(settings.baselines_dir)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create a baseline
    baseline = baselines_dir / "homepage.png"
    baseline.write_bytes(b"FAKE_PNG")

    def fake_screenshot(path=None, full_page=False):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"FAKE_PNG")

    page.screenshot.side_effect = fake_screenshot

    # Mock Pillow
    mock_img = MagicMock()
    mock_img.size = (100, 100)
    mock_img.convert.return_value = mock_img
    mock_img.resize.return_value = mock_img

    mock_diff = MagicMock()
    # Very few changed pixels → 0.1%
    mock_diff.getdata.return_value = [5] * 9990 + [100] * 10  # 10/10000 = 0.1%

    with (
        patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm),
        patch("src.tools.browser_tool.Image") as mock_image_mod,
        patch("src.tools.browser_tool.ImageChops") as mock_chops,
    ):
        mock_image_mod.open.return_value = mock_img
        mock_image_mod.LANCZOS = 1
        mock_chops.difference.return_value = mock_diff

        result = visual_regression(
            store, settings, url="http://example.com", baseline_name="homepage"
        )

    assert result["match"] is True
    assert result["diff_pct"] <= 2.0
    assert result["action"] == "compared"


def test_visual_regression_mismatch(store, settings, tmp_path):
    """diff_pct=10.5, match=False."""
    sync_pw_cm, page = _make_playwright_mock()
    settings = settings.model_copy(
        update={
            "screenshots_dir": str(tmp_path / "screenshots"),
            "baselines_dir": str(tmp_path / "baselines"),
        }
    )

    screenshots_dir = Path(settings.screenshots_dir)
    baselines_dir = Path(settings.baselines_dir)
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir.mkdir(parents=True, exist_ok=True)

    baseline = baselines_dir / "homepage.png"
    baseline.write_bytes(b"FAKE_PNG")

    def fake_screenshot(path=None, full_page=False):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"FAKE_PNG")

    page.screenshot.side_effect = fake_screenshot

    mock_img = MagicMock()
    mock_img.size = (100, 100)
    mock_img.convert.return_value = mock_img
    mock_img.resize.return_value = mock_img

    mock_diff = MagicMock()
    mock_diff.save = MagicMock()
    # 1050/10000 = 10.5%
    mock_diff.getdata.return_value = [200] * 1050 + [5] * 8950

    with (
        patch("src.tools.browser_tool.sync_playwright", return_value=sync_pw_cm),
        patch("src.tools.browser_tool.Image") as mock_image_mod,
        patch("src.tools.browser_tool.ImageChops") as mock_chops,
    ):
        mock_image_mod.open.return_value = mock_img
        mock_image_mod.LANCZOS = 1
        mock_chops.difference.return_value = mock_diff

        result = visual_regression(
            store, settings, url="http://example.com", baseline_name="homepage"
        )

    assert result["match"] is False
    assert result["diff_pct"] > 2.0
