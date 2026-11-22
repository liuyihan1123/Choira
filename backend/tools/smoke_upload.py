"""浏览器端完整走一遍：上传总谱 → 自动识别声部 → 发布 → 团员端看到新分谱。

    .venv/bin/python tools/smoke_upload.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "samples" / "bwv66_6.musicxml"
SHOTS = ROOT / "data" / "screenshots"


def main() -> int:
    if not SAMPLE.exists():
        print(f"缺少样例：{SAMPLE}，先运行 tools/fetch_public_score.py --corpus bwv66.6")
        return 1
    SHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1.5)
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(BASE, wait_until="networkidle")
        page.get_by_role("button", name="管理台").click()
        page.wait_for_selector(".upload-card")

        page.locator(".dropzone input[type=file]").set_input_files(str(SAMPLE))
        page.get_by_role("button", name="入库并解析声部").click()
        page.wait_for_selector(".matrix", timeout=20_000)

        rows = page.locator(".matrix tbody tr").count()
        title = page.locator(".version-head h2").inner_text()
        print(f"uploaded: {title} | matrix rows = {rows}")
        if rows != 4:
            errors.append(f"期望 4 个声部，实际 {rows}")

        page.screenshot(path=str(SHOTS / "admin-upload.png"), full_page=True)

        page.get_by_role("button", name="发布分谱", exact=True).click()
        page.wait_for_selector(".status-chip.published", timeout=20_000)
        print("published ok")

        # 团员端应立即可见
        page.get_by_role("button", name="团员端").click()
        page.wait_for_timeout(1500)
        visible = page.locator(".score-card").count()
        print(f"member library cards = {visible}")
        page.screenshot(path=str(SHOTS / "member-after-upload.png"), full_page=True)

        browser.close()

    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
