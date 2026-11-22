"""声部音频：速度对齐、按 part 独立出音轨、播放接口。

最重要的一条是 `test_parts_stay_aligned_*`：总谱的速度标记通常只写在
其中一个声部里，如果逐声部单独渲染，那个声部按谱面速度走、其它声部回落到
Verovio 默认 120 BPM，同一首曲子的音轨就会错位。前端是「所有音轨从同一
时刻起播」来对齐的，所以各声部时长必须一致。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app
from app.services import audio
from app.services import musicxml as mx

DEMO = Path(store.BASE_DIR) / "data" / "demo" / "demo_satb.musicxml"


@pytest.fixture(scope="module")
def doc():
    return mx.parse_score(DEMO.read_bytes(), "demo_satb.musicxml")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def score(client):
    response = client.post(
        "/api/scores",
        files={"file": ("demo_satb.musicxml", DEMO.read_bytes(), "application/xml")},
        data={"title": "音频测试曲目", "composer": "Tester"},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 合成链路
# ---------------------------------------------------------------------------

def test_tempo_map_is_taken_from_the_whole_score(doc):
    tempos = mx.collect_tempos(doc)
    assert tempos, "演示总谱应该带速度标记"
    assert all(20 <= bpm <= 300 for bpm in tempos.values()), tempos


def test_parts_stay_aligned_when_tempo_lives_in_one_part(doc):
    tempos = mx.collect_tempos(doc)
    durations: dict[str, float] = {}
    for part in doc.parts:
        xml = mx.extract_parts(doc, [part.part_id], tempos=tempos)
        notes, duration = audio.midi_to_notes(audio.musicxml_to_midi(xml))
        assert notes, f"{part.name} 应该有音符"
        durations[part.part_id] = duration

    spread = max(durations.values()) - min(durations.values())
    assert spread < 0.1, f"各声部时长必须一致，实际：{durations}"


def test_render_produces_playable_mp3(doc):
    tempos = mx.collect_tempos(doc)
    xml = mx.extract_parts(doc, ["P2"], tempos=tempos)
    mp3, duration, note_count = audio.render_part_audio(xml)

    assert mp3[0] == 0xFF and mp3[1] in (0xFB, 0xF3, 0xF2), "应当是 MP3 帧头"
    assert duration > 5.0
    assert note_count >= 10
    # 128kbps 单声道约 16KB/s，给一个宽松的下限
    assert len(mp3) / duration > 2000


def test_part_without_notes_is_rejected():
    empty = b"""<?xml version="1.0"?>
    <score-partwise version="4.0">
      <part-list><score-part id="P1"><part-name>Empty</part-name></score-part></part-list>
      <part id="P1"><measure number="1"><attributes><divisions>1</divisions></attributes>
        <note><rest/><duration>4</duration></note></measure></part>
    </score-partwise>"""
    with pytest.raises(audio.AudioError):
        audio.render_part_audio(empty)


def test_synthesized_pitch_matches_the_score(doc):
    """合成的第一个音，主频必须落在谱面写的那个音高上（半音以内）。"""
    import numpy as np

    tempos = mx.collect_tempos(doc)
    xml = mx.extract_parts(doc, ["P2"], tempos=tempos)
    notes, total = audio.midi_to_notes(audio.musicxml_to_midi(xml))
    samples = audio.synth_piano(notes, total)

    first = notes[0]
    sample_rate = audio.SAMPLE_RATE
    start = int((first.start + 0.12) * sample_rate)
    window = samples[start:start + int(0.5 * sample_rate)]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1 / sample_rate)
    peak = float(freqs[int(np.argmax(spectrum))])
    expected = 440.0 * 2 ** ((first.pitch - 69) / 12)

    assert abs(12 * np.log2(peak / expected)) < 0.5, f"主频 {peak:.1f}Hz 偏离 {expected:.1f}Hz"
    assert float(np.sqrt((samples ** 2).mean())) > 0.05, "整段不应该接近静音"


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

def test_playlist_lists_every_part_regardless_of_role(client, score):
    version_id = score["version_id"]
    published = client.post(f"/api/versions/{version_id}/publish", json={})
    assert published.status_code == 200, published.text

    data = client.get(f"/api/play/{version_id}").json()
    available = [p for p in data["parts"] if p["available"]]
    assert {p["part_id"] for p in available} == {"P1", "P2", "P3", "P4", "P5"}
    assert data["duration"] > 5.0

    durations = [p["duration"] for p in available]
    assert max(durations) - min(durations) < 0.1, durations
    assert all(p["audio_url"].endswith(p["part_id"]) for p in available)


def test_audio_endpoint_serves_mp3_with_range(client, score):
    url = f"/api/audio/{score['version_id']}/P2"

    full = client.get(url)
    assert full.status_code == 200, full.text
    assert full.headers["content-type"] == "audio/mpeg"
    assert full.headers["accept-ranges"] == "bytes"
    assert full.content[0] == 0xFF

    partial = client.get(url, headers={"Range": "bytes=0-999"})
    assert partial.status_code == 206
    assert len(partial.content) == 1000
    assert partial.headers["content-range"].startswith("bytes 0-999/")

    tail = client.get(url, headers={"Range": "bytes=-100"})
    assert tail.status_code == 206
    assert len(tail.content) == 100


def test_audio_endpoints_report_missing_things(client, score):
    version_id = score["version_id"]
    assert client.get(f"/api/audio/{version_id}/P9").status_code == 404
    assert client.get("/api/play/v_does_not_exist").status_code == 404


def test_listen_is_audited(client, score):
    client.get(f"/api/play/{score['version_id']}")
    actions = {entry["action"] for entry in client.get("/api/audit?limit=100").json()["items"]}
    assert "audio-render" in actions
    assert "listen" in actions
