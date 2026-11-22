"""用真实浏览器做一次端到端冒烟：团员看谱是否渲染、管理台是否可交互。

用法：
    .venv/bin/pip install playwright
    .venv/bin/python tools/smoke_ui.py [http://127.0.0.1:8000]

默认使用系统安装的 Chrome（channel="chrome"），不额外下载浏览器。
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SHOTS = Path(__file__).resolve().parents[1] / "data" / "screenshots"


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100}, device_scale_factor=1.5)
        page.on("console", lambda msg: problems.append(f"[console:{msg.type}] {msg.text}")
                if msg.type in ("error", "warning") else None)
        page.on("pageerror", lambda exc: problems.append(f"[pageerror] {exc}"))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".osmd-host svg", timeout=30_000)
        page.wait_for_timeout(1200)
        svg_count = page.locator(".osmd-host svg").count()
        paths = page.locator(".osmd-host svg path, .osmd-host svg text").count()
        print(f"member: {svg_count} page(s), {paths} drawable nodes")
        if paths < 50:
            problems.append("乐谱几乎没有绘制内容，可能是字体/渲染问题")
        page.screenshot(path=str(SHOTS / "member.png"), full_page=True)

        # 切到伴奏角色，验证分谱切换
        page.get_by_role("button", name="伴奏").click()
        page.wait_for_timeout(2500)
        page.screenshot(path=str(SHOTS / "member-accomp.png"), full_page=True)

        # 管理台：第一行通常是最新的 PDF 版本，验证"待识别 + 回填"面板
        page.get_by_role("button", name="管理台").click()
        page.wait_for_selector(".score-table-card", timeout=15_000)
        page.screenshot(path=str(SHOTS / "admin-list.png"), full_page=True)
        page.locator("tr", has_text="PDF 版总谱").get_by_role("button", name="管理").click()
        page.wait_for_selector(".pdf-block", timeout=15_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=str(SHOTS / "admin-pdf.png"), full_page=True)
        print("admin: pdf pending panel ok")

        # 再打开已发布的 MusicXML 版本，验证映射矩阵
        page.locator("tr", has_text="Ubi caritas (示例)").get_by_role("button", name="管理").click()
        page.wait_for_selector(".matrix", timeout=15_000)
        rows = page.locator(".matrix tbody tr").count()
        print(f"admin: mapping matrix rows = {rows}")
        page.screenshot(path=str(SHOTS / "admin.png"), full_page=True)

        page.get_by_role("button", name="审计日志").click()
        page.wait_for_timeout(800)
        page.screenshot(path=str(SHOTS / "audit.png"), full_page=True)

        browser.close()

    print("problems:", len(problems))
    for item in problems[:20]:
        print(" -", item)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
