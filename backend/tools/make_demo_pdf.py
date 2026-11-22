"""把示例总谱排成 PDF（Verovio 服务端雕刻 + Chrome 打印），用来演示"PDF 上传"流程。

用法：.venv/bin/python tools/make_demo_pdf.py
产物：data/demo/demo_full_score.pdf
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import verovio
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[1]
SOURCE = BASE / "data" / "demo" / "demo_satb.musicxml"
TARGET = BASE / "data" / "demo" / "demo_full_score.pdf"

PAGE_W, PAGE_H = 2100, 2970  # 1/10 mm → A4


def render_svg_pages(xml: str) -> list[str]:
    tk = verovio.toolkit()
    tk.setOptions({
        "pageWidth": PAGE_W,
        "pageHeight": PAGE_H,
        "scale": 40,
        "adjustPageHeight": False,
        "breaks": "auto",
    })
    tk.loadData(xml)
    count = tk.getPageCount()
    return [tk.renderToSVG(i + 1) for i in range(count)]


def main() -> None:
    xml = SOURCE.read_text(encoding="utf-8")
    pages = render_svg_pages(xml)
    print(f"verovio pages: {len(pages)}")

    html = [
        "<!doctype html><meta charset='utf-8'>",
        "<title>Ubi caritas · 合唱总谱</title>",
        "<style>",
        "@page { size: A4; margin: 0 }",
        "html,body{margin:0;padding:0;background:#fff}",
        ".page{width:210mm;height:297mm;overflow:hidden;page-break-after:always;position:relative}",
        ".page:last-child{page-break-after:auto}",
        ".page svg{width:100%;height:auto;display:block}",
        "</style>",
    ]
    for svg in pages:
        html.append(f"<div class='page'>{svg}</div>")

    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "score.html"
        page_file.write_text("".join(html), encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.goto(page_file.as_uri(), wait_until="load")
            page.wait_for_timeout(400)
            page.pdf(path=str(TARGET), format="A4", print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
            browser.close()

    print(f"written {TARGET} ({TARGET.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
