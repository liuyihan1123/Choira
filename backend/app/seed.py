"""演示数据：首次启动时把 data/demo 下的示例总谱灌进库，让页面一打开就有内容。"""

from __future__ import annotations

from pathlib import Path

from . import pipeline, store

DEMO_XML = "demo_satb.musicxml"
DEMO_PDF = "demo_full_score.pdf"


def seed_demo() -> None:
    store.init_db()
    if pipeline.stats()["scores"] > 0:
        return

    xml_path = store.DEMO_DIR / DEMO_XML
    if xml_path.exists():
        try:
            detail = pipeline.create_score(
                xml_path.read_bytes(), DEMO_XML, "Ubi caritas (示例)", "ChoirParts Demo"
            )
            if detail.get("mapping"):
                pipeline.publish(detail["version_id"])
        except Exception as exc:  # pragma: no cover - 演示数据坏了不应阻止启动
            print(f"[seed] 示例总谱导入失败：{exc}")

    # 真实语料（music21 导出的巴赫四声部众赞歌，公有领域）
    sample = store.DATA_DIR / "samples" / "bwv66_6.musicxml"
    if sample.exists():
        try:
            detail = pipeline.create_score(
                sample.read_bytes(), sample.name, "Bach 众赞歌 bwv66.6", "J. S. Bach"
            )
            if detail.get("mapping"):
                pipeline.publish(detail["version_id"])
        except Exception as exc:  # pragma: no cover
            print(f"[seed] 真实语料导入失败：{exc}")

    pdf_path = store.DEMO_DIR / DEMO_PDF
    if pdf_path.exists():
        try:
            pipeline.create_score(pdf_path.read_bytes(), DEMO_PDF, "Ubi caritas（PDF 版总谱）", "PDF 上传示例")
        except Exception as exc:  # pragma: no cover
            print(f"[seed] 示例 PDF 导入失败：{exc}")


if __name__ == "__main__":  # 手动重建演示库：python -m app.seed
    seed_demo()
    print("seeded", pipeline.stats())
