"""MusicXML → MIDI（Verovio）→ 钢琴音色合成 → MP3。

为什么自己合成而不接 fluidsynth/音源：
项目本来就不想引入外部二进制与几十 MB 的音源文件，而排练听音只需要
「音高 + 节奏 + 声部进出」准确，音色好听排第二位。这里用 numpy 写一个
加性合成器（10 个泛音 + 轻微非谐性 + 双振荡器微失谐 + ADSR 包络），
听感接近电钢琴，足够辨认声部与和声。

每个 <part> 独立渲染一条音轨，且都来自同一份总谱的同一份 tempo map，
所以前端从同一时刻起播就能对齐，不需要任何时间拉伸。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

SAMPLE_RATE = 44100
MP3_BITRATE = 128

#: 音符结束后再留一小段余响，避免最后一个音被切断
TAIL_SECONDS = 0.6

_HARMONICS = 10


class AudioError(RuntimeError):
    """无法把这份 MusicXML 渲染成音频。"""


def dependencies_available() -> bool:
    try:
        import lameenc  # noqa: F401
        import mido  # noqa: F401
        import numpy  # noqa: F401
        import verovio  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# MusicXML -> MIDI
# ---------------------------------------------------------------------------

def _verovio_resource_path() -> str | None:
    """Verovio 自带的资源目录（字体、字形表）。

    必须显式设置：Verovio 的字体资源是在导入时绑定到主线程的，而 FastAPI 的
    同步接口跑在线程池里，不显式指定就会报 "font resources are not available"
    并让 loadData() 返回 False（看起来像「MusicXML 解析失败」，其实跟文件无关）。
    """
    try:
        from importlib.resources import files

        return str(files("verovio") / "data")
    except Exception:  # pragma: no cover - 资源目录缺失时退回 Verovio 默认行为
        return None


def musicxml_to_midi(xml_bytes: bytes) -> bytes:
    """用 Verovio 把 MusicXML 转成标准 MIDI（连音线、附点、复调都交给它）。"""
    try:
        import verovio
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise AudioError("缺少 verovio，无法生成音频（pip install verovio）") from exc

    toolkit = verovio.toolkit()
    resource_path = _verovio_resource_path()
    if resource_path:
        try:
            toolkit.setResourcePath(resource_path)
        except Exception:  # pragma: no cover - 老版本没有这个方法
            pass
    try:
        loaded = toolkit.loadData(xml_bytes.decode("utf-8", errors="replace"))
    except Exception as exc:  # pragma: no cover - Verovio 内部错误
        raise AudioError(f"Verovio 读取 MusicXML 失败：{exc}") from exc
    if not loaded:
        raise AudioError("Verovio 无法解析这份 MusicXML")
    rendered = toolkit.renderToMIDI()
    if not rendered:
        raise AudioError("Verovio 没有产出 MIDI")
    if isinstance(rendered, str):
        try:
            return base64.b64decode(rendered, validate=False)
        except Exception as exc:  # pragma: no cover
            raise AudioError("MIDI 数据解码失败") from exc
    return bytes(rendered)


@dataclass
class NoteEvent:
    start: float
    duration: float
    pitch: int
    velocity: int


def midi_to_notes(midi_bytes: bytes) -> tuple[list[NoteEvent], float]:
    """解析 MIDI，返回 (音符事件, 总时长秒)。

    `mido` 迭代 MidiFile 时会把时间统一换算成秒，并且自动合并所有轨道、
    跟随 set_tempo 变化，所以这里不必自己处理 tick 与 tempo。
    """
    import io

    import mido

    try:
        mid = mido.MidiFile(file=io.BytesIO(midi_bytes))
    except Exception as exc:
        raise AudioError(f"MIDI 解析失败：{exc}") from exc

    now = 0.0
    pending: dict[int, list[tuple[float, int]]] = {}
    notes: list[NoteEvent] = []
    for msg in mid:  # 已按绝对时间合并全部轨道
        now += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            pending.setdefault(msg.note, []).append((now, msg.velocity))
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            queue = pending.get(msg.note)
            if queue:
                start, velocity = queue.pop(0)
                notes.append(NoteEvent(start, max(now - start, 0.02), msg.note, velocity))

    total = max([now] + [n.start + n.duration for n in notes])
    for pitch, queue in pending.items():  # 忘记 note_off 的音符按结尾补齐
        for start, velocity in queue:
            notes.append(NoteEvent(start, max(total - start, 0.02), pitch, velocity))

    notes.sort(key=lambda n: n.start)
    return notes, total


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------

def synth_piano(notes: list[NoteEvent], duration: float,
                sample_rate: int = SAMPLE_RATE) -> "object":
    """把音符事件渲染成单声道 float64 波形（-1~1）。"""
    import numpy as np

    total_samples = max(int((duration + TAIL_SECONDS) * sample_rate), sample_rate // 10)
    buffer = np.zeros(total_samples, dtype=np.float64)
    if not notes:
        return buffer

    attack = 0.006      # 起音 6ms，避免爆音
    release = 0.09      # 离键释放
    sustain_level = 0.22

    for event in notes:
        freq = 440.0 * 2.0 ** ((event.pitch - 69) / 12.0)
        if freq <= 0 or freq >= sample_rate / 2:
            continue

        length = event.duration + release
        start_sample = int(event.start * sample_rate)
        count = min(int(length * sample_rate), total_samples - start_sample)
        if count <= 2:
            continue

        t = np.arange(count, dtype=np.float64) / sample_rate
        envelope = np.ones(count, dtype=np.float64)

        attack_samples = max(int(attack * sample_rate), 1)
        envelope[:attack_samples] = np.linspace(0.0, 1.0, attack_samples, endpoint=False)

        # 低音衰减慢、高音衰减快，接近真实琴弦
        tau = float(np.clip(1.9 * (220.0 / freq) ** 0.35, 0.35, 2.4))
        envelope *= sustain_level + (1.0 - sustain_level) * np.exp(-t / tau)

        # 只有音符结束之后才开始释放
        envelope *= np.clip((length - t) / release, 0.0, 1.0)

        amplitude = (event.velocity / 127.0) ** 1.2 * 0.30

        wave = np.zeros(count, dtype=np.float64)
        for harmonic in range(1, _HARMONICS + 1):
            partial = harmonic * freq * (1.0 + 2.2e-4 * harmonic * harmonic)
            if partial >= sample_rate * 0.45:
                break
            wave += (1.0 / harmonic ** 1.55) * np.sin(2.0 * np.pi * partial * t)

        # 一层微失谐的基音，做出「两根弦」的厚度
        wave = 0.75 * wave + 0.25 * np.sin(2.0 * np.pi * freq * 1.0016 * t)

        buffer[start_sample:start_sample + count] += wave * envelope * amplitude

    peak = float(np.max(np.abs(buffer))) if buffer.size else 0.0
    if peak > 0:
        buffer *= 0.9 / peak
    return buffer


def encode_mp3(samples, sample_rate: int = SAMPLE_RATE,
               bitrate: int = MP3_BITRATE) -> bytes:
    """把 -1~1 的波形编成单声道 MP3。"""
    import lameenc
    import numpy as np

    pcm = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    pcm = (pcm * 32000).astype("<i2").tobytes()

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate)
    encoder.set_in_sample_rate(sample_rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    encoded = encoder.encode(pcm) + encoder.flush()
    return bytes(encoded)


def render_part_audio(xml_bytes: bytes) -> tuple[bytes, float, int]:
    """分谱 MusicXML → (MP3 字节, 时长秒, 音符数)。"""
    midi = musicxml_to_midi(xml_bytes)
    notes, duration = midi_to_notes(midi)
    if not notes:
        raise AudioError("该声部没有可发声的音符")
    samples = synth_piano(notes, duration)
    mp3 = encode_mp3(samples)
    if not mp3:
        raise AudioError("音频编码失败")
    return mp3, round(len(samples) / SAMPLE_RATE, 3), len(notes)
