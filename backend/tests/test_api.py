"""端到端 API 测试：上传 → 映射 → 发布 → 按角色取谱 → 签名下载。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app

DEMO = Path(store.BASE_DIR) / "data" / "demo" / "demo_satb.musicxml"

REDUCTION = """<?xml version="1.0" encoding="UTF-8"?>
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


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:  # 触发 lifespan（建表 + 空库不灌演示数据）
        yield test_client


@pytest.fixture(scope="module")
def score(client):
    raw = DEMO.read_bytes()
    response = client.post(
        "/api/scores",
        files={"file": ("demo_satb.musicxml", raw, "application/xml")},
        data={"title": "测试曲目", "composer": "Tester"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_parses_parts_and_prefills_mapping(score):
    assert score["status"] == "draft"
    assert [p["name"] for p in score["parts"]] == ["Soprano", "Alto", "Tenor", "Bass", "Piano"]
    assert score["mapping"] == {"ACCOMP": ["P5"], "S": ["P1"], "A": ["P2"], "T": ["P3"], "B": ["P4"]}
    assert score["unsplittable_parts"] == []


def test_publish_creates_one_asset_per_assignment(client, score):
    response = client.post(f"/api/versions/{score['version_id']}/publish", json={})
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "published"
    assert detail["asset_count"] == 5
    assert detail["published_at"]

    again = client.post(f"/api/versions/{score['version_id']}/publish", json={})
    assert again.status_code == 400
    assert "已发布" in again.json()["detail"]


def test_role_library_only_exposes_own_part(client, score):
    library = client.get("/api/library/S").json()
    item = next(i for i in library["items"] if i["version_id"] == score["version_id"])
    assert [a["part_name"] for a in item["assets"]] == ["Soprano"]

    accomp = client.get("/api/library/ACCOMP").json()["items"]
    accomp_item = next(i for i in accomp if i["version_id"] == score["version_id"])
    assert [a["part_name"] for a in accomp_item["assets"]] == ["Piano"]

    # 男高音拿不到女高音的 asset id
    soprano_asset = item["assets"][0]["id"]
    xml = client.get(f"/api/assets/{soprano_asset}?role=S")
    assert xml.status_code == 200
    assert "女高音" in xml.text and "watermark" in xml.text
    assert xml.text.count("<score-part ") == 1
    assert "<lyric" in xml.text


def test_signed_download_token(client, score):
    asset_id = client.get("/api/library/B").json()["items"][0]["assets"][0]["id"]
    signed = client.post(f"/api/assets/{asset_id}/sign?role=B").json()
    assert signed["url"].startswith("/api/dl/")

    download = client.get(signed["url"])
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert "Bass" in download.text

    assert client.get("/api/dl/not-a-real-token").status_code == 410


def test_multi_voice_part_requires_force(client):
    response = client.post(
        "/api/scores",
        files={"file": ("reduction.musicxml", REDUCTION.encode(), "application/xml")},
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["unsplittable_parts"] == ["Choir"]
    assert detail["parts"][0]["extractable"] is False

    mapped = client.put(
        f"/api/versions/{detail['version_id']}/assignments",
        json={"mapping": {"ACCOMP": ["P1"]}},
    )
    assert mapped.status_code == 200, mapped.text

    # 默认拒绝
    rejected = client.post(f"/api/versions/{detail['version_id']}/publish", json={})
    assert rejected.status_code == 400
    assert "强制发布" in rejected.json()["detail"]

    forced = client.post(f"/api/versions/{detail['version_id']}/publish", json={"force": True})
    assert forced.status_code == 200, forced.text
    assert forced.json()["status"] == "published"


def test_pdf_flow_pending_then_attach(client):
    pdf_bytes = (Path(store.BASE_DIR) / "data" / "demo" / "demo_full_score.pdf").read_bytes()
    response = client.post(
        "/api/scores",
        files={"file": ("full-score.pdf", pdf_bytes, "application/pdf")},
        data={"title": "PDF 案例"},
    )
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["status"] == "pending_omr"
    assert detail["has_pdf"] and not detail["has_musicxml"]
    assert detail["parts"] == []

    pdf = client.get(f"/api/versions/{detail['version_id']}/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")

    # 回填 OMR 结果后进入同一条流水线
    attached = client.post(
        f"/api/versions/{detail['version_id']}/attach-musicxml",
        files={"file": ("converted.musicxml", DEMO.read_bytes(), "application/xml")},
    )
    assert attached.status_code == 200, attached.text
    updated = attached.json()
    assert updated["status"] == "draft"
    assert updated["source_kind"] == "pdf+musicxml"
    assert len(updated["parts"]) == 5


def test_audit_records_views(client, score):
    entries = client.get("/api/audit?limit=100").json()["items"]
    actions = {entry["action"] for entry in entries}
    assert {"upload", "publish", "view", "download"} <= actions
