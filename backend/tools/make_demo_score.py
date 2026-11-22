"""生成演示用 SATB + 钢琴总谱（MusicXML 4.0）。

刻意做成"结构规整的四声部 + 钢琴伴奏"，用来演示：
- 上传总谱 → 自动识别 5 个 part → 名称归一化成 S/A/T/B/伴奏 → 发布 5 份分谱
- 歌词在拆分后仍然保留（XML 级裁剪的好处）
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from lxml import etree

VERSION = "4.0"
DIVISIONS = 1
KEY_FIFTHS = -1          # F 大调
TEMPO = 76

STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

# (音名, 八度, 时值[拍])；divisions=1 → 四分音符 = 1
BARS = [
    # A 段（前 8 小节）
    dict(s=[("A", 4, 2), ("A", 4, 2)], a=[("F", 4, 4)], t=[("C", 4, 4)], b=[("F", 3, 4)],
         lyr=["U", "bi"], piano=(["F4", "A4", "C5"], "F2")),
    dict(s=[("A", 4, 2), ("A", 4, 2)], a=[("F", 4, 4)], t=[("D", 4, 4)], b=[("D", 3, 4)],
         lyr=["ca", "ri"], piano=(["F4", "A4", "D5"], "D2")),
    dict(s=[("B", 4, 2), ("B", 4, 2)], a=[("F", 4, 4)], t=[("D", 4, 4)], b=[("B", 3, 4)],
         lyr=["tas", "et"], piano=(["F4", "Bb4", "D5"], "Bb2")),
    dict(s=[("C", 5, 2), ("C", 5, 2)], a=[("G", 4, 4)], t=[("E", 4, 4)], b=[("C", 3, 4)],
         lyr=["a", "mor"], piano=(["E4", "G4", "C5"], "C3")),
    dict(s=[("A", 4, 2), ("A", 4, 2)], a=[("F", 4, 4)], t=[("C", 4, 4)], b=[("F", 3, 4)],
         lyr=["De", "us"], piano=(["F4", "A4", "C5"], "F2")),
    dict(s=[("A", 4, 2), ("A", 4, 2)], a=[("F", 4, 4)], t=[("D", 4, 4)], b=[("D", 3, 4)],
         lyr=["i", "bi"], piano=(["F4", "A4", "D5"], "D2")),
    dict(s=[("B", 4, 2), ("C", 5, 2)], a=[("F", 4, 2), ("G", 4, 2)],
         t=[("D", 4, 2), ("E", 4, 2)], b=[("B", 3, 2), ("C", 3, 2)],
         lyr=["est,", "—"], piano=(["D4", "F4", "Bb4"], "Bb2"), piano2=(["E4", "G4", "C5"], "C3")),
    dict(s=[("A", 4, 4)], a=[("F", 4, 4)], t=[("C", 4, 4)], b=[("F", 3, 4)],
         lyr=[""], piano=(["F4", "A4", "C5"], "F2")),
    # B 段（后 8 小节，收在 Amen）
    dict(s=[("D", 5, 2), ("D", 5, 2)], a=[("B", 4, 4)], t=[("F", 4, 4)], b=[("B", 3, 4)],
         lyr=["U", "bi"], piano=(["F4", "Bb4", "D5"], "Bb2")),
    dict(s=[("E", 5, 2), ("E", 5, 2)], a=[("C", 5, 4)], t=[("G", 4, 4)], b=[("C", 3, 4)],
         lyr=["ca", "ri"], piano=(["E4", "G4", "C5"], "C3")),
    dict(s=[("F", 5, 2), ("E", 5, 2)], a=[("C", 5, 4)], t=[("A", 4, 4)], b=[("F", 3, 4)],
         lyr=["tas", "et"], piano=(["F4", "A4", "C5"], "F2")),
    dict(s=[("D", 5, 2), ("C", 5, 2)], a=[("A", 4, 4)], t=[("F", 4, 4)], b=[("D", 3, 4)],
         lyr=["a", "mor"], piano=(["F4", "A4", "D5"], "D2")),
    dict(s=[("B", 4, 2), ("D", 5, 2)], a=[("F", 4, 4)], t=[("D", 4, 4)], b=[("B", 3, 4)],
         lyr=["De", "us"], piano=(["F4", "Bb4", "D5"], "Bb2")),
    dict(s=[("E", 5, 2), ("D", 5, 2)], a=[("G", 4, 4)], t=[("C", 4, 4)], b=[("C", 3, 4)],
         lyr=["i", "bi"], piano=(["E4", "G4", "C5"], "C3")),
    dict(s=[("F", 5, 2), ("E", 5, 2)], a=[("C", 5, 4)], t=[("A", 4, 4)], b=[("F", 3, 4)],
         lyr=["est.", "A"], piano=(["F4", "A4", "C5"], "F2")),
    dict(s=[("F", 5, 4)], a=[("C", 5, 4)], t=[("A", 4, 4)], b=[("F", 3, 4)],
         lyr=["men"], piano=(["F4", "A4", "C5"], "F2")),
]


PARTS = [
    dict(id="P1", name="Soprano", abbrev="S.", clef=("G", 2), staff=1, midi=54, ch="s"),
    dict(id="P2", name="Alto", abbrev="A.", clef=("G", 2), staff=1, midi=54, ch="a"),
    dict(id="P3", name="Tenor", abbrev="T.", clef=("C", 4), staff=1, midi=53, ch="t"),
    dict(id="P4", name="Bass", abbrev="B.", clef=("F", 4), staff=1, midi=53, ch="b"),
]


def _el(parent, tag, text=None, **attrs):
    node = etree.SubElement(parent, tag)
    for key, value in attrs.items():
        node.set(key, str(value))
    if text is not None:
        node.text = str(text)
    return node


def add_pitch(parent, name: str, octave: int, duration: int, *, voice=1, staff=None, lyric=None,
              tie_stop=False):
    note = _el(parent, "note")
    if tie_stop:
        _el(note, "tie", type="stop")
    pitch = _el(note, "pitch")
    _el(pitch, "step", name[0])
    if len(name) > 1:
        _el(pitch, "alter", 1 if name[1] == "#" else -1)
    _el(pitch, "octave", octave)
    _el(note, "duration", duration)
    if tie_stop:
        notations = _el(note, "notations")
        _el(notations, "tied", type="stop")
    _el(note, "voice", voice)
    _el(note, "type", {1: "quarter", 2: "half", 3: "half", 4: "whole"}.get(duration, "quarter"))
    if staff:
        _el(note, "staff", staff)
    if lyric:
        ly = _el(note, "lyric", number=1)
        _el(ly, "syllabic", "single")
        _el(ly, "text", lyric)
    return note


def add_chord(parent, pitches: list[str], duration: int, *, voice=1, staff=None):
    for i, p in enumerate(pitches):
        note = _el(parent, "note")
        if i > 0:
            _el(note, "chord")
        pitch = _el(note, "pitch")
        _el(pitch, "step", p[0])
        if len(p) > 1 and p[1] in "#b":
            _el(pitch, "alter", 1 if p[1] == "#" else -1)
        _el(pitch, "octave", int(p[-1]))
        _el(note, "duration", duration)
        _el(note, "voice", voice)
        _el(note, "type", {1: "quarter", 2: "half", 4: "whole"}.get(duration, "quarter"))
        if staff:
            _el(note, "staff", staff)


def add_rest(parent, duration: int, *, voice=1, staff=None):
    note = _el(parent, "note")
    _el(note, "rest")
    _el(note, "duration", duration)
    _el(note, "voice", voice)
    _el(note, "type", {1: "quarter", 2: "half", 4: "whole"}[duration])
    if staff:
        _el(note, "staff", staff)


def build() -> bytes:
    root = etree.Element("score-partwise", version=VERSION)
    work = _el(root, "work")
    _el(work, "work-title", "Ubi caritas")
    _el(root, "movement-number", "1")
    _el(root, "movement-title", "Ubi caritas")

    ident = _el(root, "identification")
    _el(ident, "creator", "ChoirParts Demo", type="composer")
    _el(ident, "creator", "示例数据（原创旋律，可自由使用）", type="lyricist")
    encoding = _el(ident, "encoding")
    _el(encoding, "software", "ChoirParts demo generator")
    _el(encoding, "encoding-date", date.today().isoformat())

    defaults = _el(root, "defaults")
    scaling = _el(defaults, "scaling")
    _el(scaling, "millimeters", "7")
    _el(scaling, "tenths", "40")
    page = _el(defaults, "page-layout")
    size = _el(page, "page-height", "1683")
    size = _el(page, "page-width", "1190")
    margins = _el(page, "page-margins", type="both")
    for side in ("left", "right", "top", "bottom"):
        _el(margins, side + "-margin", "70")

    credits = (
        ("title", "Ubi caritas", "26", {"valign": "top"}),
        ("composer", "ChoirParts Demo", "12", {"valign": "bottom", "halign": "right"}),
    )
    for ctype, text, size, pos in credits:
        credit = _el(root, "credit", page="1")
        _el(credit, "credit-type", ctype)
        _el(credit, "credit-words", text, justify="center", **pos, **{"font-size": size})

    part_list = _el(root, "part-list")
    for spec in PARTS:
        sp = _el(part_list, "score-part", id=spec["id"])
        _el(sp, "part-name", spec["name"])
        _el(sp, "part-abbreviation", spec["abbrev"])
        si = _el(sp, "score-instrument", id=f'{spec["id"]}-I1')
        _el(si, "instrument-name", spec["name"])
        mi = _el(sp, "midi-instrument", id=f'{spec["id"]}-I1')
        _el(mi, "midi-channel", spec["staff"])
        _el(mi, "midi-program", spec["midi"])
    sp = _el(part_list, "score-part", id="P5")
    _el(sp, "part-name", "Piano")
    _el(sp, "part-abbreviation", "Pno.")
    si = _el(sp, "score-instrument", id="P5-I1")
    _el(si, "instrument-name", "Piano")
    mi = _el(sp, "midi-instrument", id="P5-I1")
    _el(mi, "midi-channel", "5")
    _el(mi, "midi-program", "1")

    for spec in PARTS:
        part = _el(root, "part", id=spec["id"])
        for idx, bar in enumerate(BARS):
            measure = _el(part, "measure", number=idx + 1)
            if idx == 0:
                attrs = _el(measure, "attributes")
                _el(attrs, "divisions", DIVISIONS)
                key = _el(attrs, "key")
                _el(key, "fifths", KEY_FIFTHS)
                time = _el(attrs, "time")
                _el(time, "beats", "4")
                _el(time, "beat-type", "4")
                clef = _el(attrs, "clef")
                _el(clef, "sign", spec["clef"][0])
                _el(clef, "line", spec["clef"][1])
                if len(spec["clef"]) > 2:
                    _el(clef, "clef-octave-change", spec["clef"][2])
                if spec["id"] == "P1":
                    direction = _el(measure, "direction", placement="above")
                    dtype = _el(direction, "direction-type")
                    _el(dtype, "words", "Andante", **{"font-weight": "bold"})
                    _el(direction, "sound", tempo=TEMPO)
            notes = bar[spec["ch"]]
            for i, (name, octave, dur) in enumerate(notes):
                lyric = bar["lyr"][i] if i < len(bar["lyr"]) else None
                add_pitch(measure, name, octave, dur, lyric=(lyric or None) if spec["id"] == "P1" else None)
            if idx == len(BARS) - 1:
                barline = _el(measure, "barline", location="right")
                _el(barline, "bar-style", "light-heavy")

    # 钢琴：右手两行谱表
    part = _el(root, "part", id="P5")
    for idx, bar in enumerate(BARS):
        measure = _el(part, "measure", number=idx + 1)
        if idx == 0:
            attrs = _el(measure, "attributes")
            _el(attrs, "divisions", DIVISIONS)
            key = _el(attrs, "key")
            _el(key, "fifths", KEY_FIFTHS)
            time = _el(attrs, "time")
            _el(time, "beats", "4")
            _el(time, "beat-type", "4")
            _el(attrs, "staves", 2)
            clef = _el(attrs, "clef", number=1)
            _el(clef, "sign", "G")
            _el(clef, "line", "2")
            clef = _el(attrs, "clef", number=2)
            _el(clef, "sign", "F")
            _el(clef, "line", "4")
        piano = bar["piano"]
        if bar.get("piano2"):  # 第 7 小节：两个和弦
            add_chord(measure, bar["piano"][0], 2, voice=1, staff=1)
            add_chord(measure, bar["piano2"][0], 2, voice=1, staff=1)
            backup = _el(measure, "backup")
            _el(backup, "duration", 4)
            add_pitch(measure, bar["piano"][1][0], int(bar["piano"][1][-1]), 2, voice=2, staff=2)
            add_pitch(measure, bar["piano2"][1][0], int(bar["piano2"][1][-1]), 2, voice=2, staff=2)
        else:
            chord, bass = piano
            add_chord(measure, chord, 4, voice=1, staff=1)
            backup = _el(measure, "backup")
            _el(backup, "duration", 4)
            add_pitch(measure, bass[0], int(bass[-1]), 4, voice=2, staff=2)
        if idx == len(BARS) - 1:
            barline = _el(measure, "barline", location="right")
            _el(barline, "bar-style", "light-heavy")

    body = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    doctype = b'<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">\n'
    end = body.find(b"?>") + 2
    return body[:end] + b"\n" + doctype + body[end:]


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "data" / "demo" / "demo_satb.musicxml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build())
    print(f"written {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
