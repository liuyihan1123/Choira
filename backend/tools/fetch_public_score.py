"""准备真实公共版权总谱，作为案例素材。

三种来源：
1. music21 内置语料（巴赫四声部众赞歌，公有领域）：不需要联网
       python tools/fetch_public_score.py --corpus bwv66.6
2. 直接给一个 MusicXML/MXL 链接（自己从 CPDL / IMSLP / OpenScore 拿到的直链）：
       python tools/fetch_public_score.py --url "https://.../score.mxl"
3. 手动下载（推荐）：CPDL 与 IMSLP 对脚本抓取有 Cloudflare / Cookie 拦截，
   用浏览器下载最省事，下载后把文件拖进管理台上传即可。

产物默认写到 backend/data/samples/。
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ChoirParts/0.1"}


def from_corpus(work: str) -> Path:
    from music21 import corpus

    score = corpus.parse(work)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUT_DIR / f"{work.replace('.', '_')}.musicxml"
    score.write("musicxml", fp=str(target))
    print(f"music21 语料 {work} → {target}")
    return target


def from_url(url: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    name = url.rstrip("/").split("/")[-1] or "downloaded.musicxml"
    target = OUT_DIR / name
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=30) as response:
        target.write_bytes(response.read())
    print(f"{url} → {target} ({target.stat().st_size} bytes)")
    return target


def print_manual_hint() -> None:
    print(
        "\n手动下载建议：\n"
        "  MusicXML：https://www.cpdl.org 搜 SATB 作品（页面里选 MusicXML 格式），"
        "或用 https://openscore.org 的公开曲目\n"
        "  PDF 总谱：https://imslp.org 搜作品 → Full Score\n"
        "  两处都有反爬，脚本直连会被 403，用浏览器下载后直接拖进管理台即可。"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", help="music21 语料编号，例如 bwv66.6 / bwv227")
    parser.add_argument("--url", help="MusicXML / MXL 直链")
    args = parser.parse_args()

    if args.corpus:
        from_corpus(args.corpus)
    elif args.url:
        from_url(args.url)
    else:
        parser.print_help()
        print_manual_hint()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
