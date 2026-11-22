"""核心链路单元测试：python -m pytest -q"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from app.services import musicxml as mx
from app.services.role_detect import suggest_role

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo" / "demo_satb.musicxml"


def _demo_bytes() -> bytes:
    if not DEMO.exists():
        pytest.skip("演示总谱未生成：先运行 python tools/make_demo_score.py")
    return DEMO.read_bytes()


def test_parse_demo_parts_and_roles():
    doc = mx.parse_score(_demo_bytes(), "demo_satb.musicxml")
    assert doc.title == "Ubi caritas"
    assert [p.name for p in doc.parts] == ["Soprano", "Alto", "Tenor", "Bass", "Piano"]
    assert [p.suggested_role for p in doc.parts] == ["S", "A", "T", "B", "ACCOMP"]
    assert all(p.extractable for p in doc.parts)
    piano = doc.parts[-1]
    assert piano.staves == 2 and piano.voices == ["1", "2"]


def test_extract_single_part_keeps_music_and_drops_layout_hints():
    doc = mx.parse_score(_demo_bytes(), "demo.musicxml")
    xml = mx.extract_parts(doc, ["P1"], watermark="女高音 · v1")
    out = mx.parse_score(xml, "soprano.musicxml")

    assert [p.part_id for p in out.parts] == ["P1"]
    assert out.parts[0].name == "Soprano"
    text = xml.decode()
    assert "<part-list>" in text and text.count("<score-part ") == 1
    for gone in ("P2", "P3", "P4", "P5"):
        assert f'score-part id="{gone}"' not in text
    assert "new-system" not in text and "new-page" not in text
    assert "<lyric" in text, "歌词必须保留"
    assert "女高音 · v1" in text, "水印写入 miscellaneous"
    assert text.startswith("<?xml")


def test_extract_multiple_parts():
    doc = mx.parse_score(_demo_bytes(), "demo.musicxml")
    xml = mx.extract_parts(doc, ["P1", "P2"])
    out = mx.parse_score(xml, "sa.musicxml")
    assert [p.part_id for p in out.parts] == ["P1", "P2"]


def test_mxl_zip_is_unpacked():
    xml_bytes = _demo_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles>'
            '<rootfile full-path="score.xml" media-type="application/vnd.recordare.musicxml+xml"/>'
            "</rootfiles></container>",
        )
        zf.writestr("score.xml", xml_bytes)
    doc = mx.parse_score(buffer.getvalue(), "demo.mxl")
    assert len(doc.parts) == 5


def test_multi_voice_part_flagged_unsplittable():
    """SATB 叠在钢琴双谱表上的情形：必须被标为不可按 part 拆分。"""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Choir</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><staves>2</staves>
        <clef number="1"><sign>G</sign><line>2</line></clef>
        <clef number="2"><sign>F</sign><line>4</line></clef>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice><staff>1</staff></note>
      <backup><duration>4</duration></backup>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>2</voice><staff>1</staff></note>
      <backup><duration>4</duration></backup>
      <note><pitch><step>G</step><octave>3</octave></pitch><duration>4</duration><voice>5</voice><staff>2</staff></note>
      <backup><duration>4</duration></backup>
      <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><voice>6</voice><staff>2</staff></note>
    </measure>
  </part>
</score-partwise>"""
    doc = mx.parse_score(xml.encode(), "reduction.musicxml")
    part = doc.parts[0]
    assert part.multi_voice and not part.extractable
    assert part.warnings, "必须给出人类可读的警告"


def test_timewise_rejected_with_hint():
    xml = b'<?xml version="1.0"?><score-timewise version="4.0"><part-list/></score-timewise>'
    with pytest.raises(mx.MusicXmlError) as exc:
        mx.parse_score(xml, "timewise.xml")
    assert "score-partwise" in str(exc.value)


def test_role_suggestions():
    assert suggest_role("Soprano")[0] == "S"
    assert suggest_role("S.")[0] == "S"
    assert suggest_role("女低音")[0] == "A"
    assert suggest_role("Bass")[0] == "B"
    assert suggest_role("Piano")[0] == "ACCOMP"
    assert suggest_role("Bassoon")[0] != "B"
    assert suggest_role("Choir")[0] is None
