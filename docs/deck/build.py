"""把 index.html 里的截图内联成 base64，产出可以单文件分发的 HTML 课件。

    python build.py
产物：docs/合唱团分谱系统-开发流程.html
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "index.html"
TARGET = HERE.parent / "合唱团分谱系统-开发流程.html"


def main() -> None:
    html = SOURCE.read_text(encoding="utf-8")

    def inline(match: re.Match[str]) -> str:
        rel = match.group(1)
        path = HERE / rel
        if not path.exists():
            raise SystemExit(f"缺少图片：{path}")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return f'src="data:image/png;base64,{data}"'

    html, count = re.subn(r'src="(assets/[^"]+)"', inline, html)
    TARGET.write_text(html, encoding="utf-8")
    print(f"inlined {count} images → {TARGET} ({TARGET.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
