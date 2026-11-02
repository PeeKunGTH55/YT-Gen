from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.paths import load_yaml, resolve_clip_dir


def tokenize_thai_words(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    try:
        from pythainlp.tokenize import word_tokenize

        tokens = word_tokenize(cleaned, engine="newmm", keep_whitespace=False)
        return [t.strip() for t in tokens if t.strip()]
    except Exception:
        # Fallback if pythainlp is unavailable
        parts = re.findall(r"[ก-๙]+|[a-zA-Z0-9]+|[^\sก-๙a-zA-Z0-9]+", cleaned)
        return [p for p in parts if p.strip()]


def group_tokens_into_chunks(
    tokens: list[str], min_words: int = 3, max_words: int = 6
) -> list[str]:
    if not tokens:
        return []
    chunks: list[str] = []
    idx = 0
    total = len(tokens)
    while idx < total:
        remaining = total - idx
        if remaining <= max_words:
            chunks.append("".join(tokens[idx:]))
            break
        step = max_words
        if remaining - step < min_words:
            step = max(min_words, remaining // 2)
        chunks.append("".join(tokens[idx : idx + step]))
        idx += step
    return chunks


def format_ass_time(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    cs = total_cs % 100
    total_sec = total_cs // 100
    s = total_sec % 60
    total_min = total_sec // 60
    m = total_min % 60
    h = total_min // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def highlight_chunk_text(
    chunk: str,
    emphasis_words: list[str],
    primary_color: str,
    highlight_color: str,
) -> str:
    result = chunk
    for word in sorted(set(emphasis_words), key=len, reverse=True):
        w = word.strip()
        if not w or w not in result:
            continue
        tag_open = f"{{\\c{highlight_color}&\\fscx108\\fscy108}}"
        tag_close = f"{{\\c{primary_color}&\\fscx100\\fscy100}}"
        result = result.replace(w, f"{tag_open}{w}{tag_close}")
    return result


def build_ass_header(channel_cfg: dict[str, Any], safe_cfg: dict[str, Any]) -> str:
    sub_cfg = channel_cfg.get("subtitles", {})
    canvas = safe_cfg.get("canvas", {"width": 1080, "height": 1920})
    width = int(canvas.get("width", 1080))
    height = int(canvas.get("height", 1920))

    font_name = sub_cfg.get("font_name", "Tahoma")
    font_size = int(sub_cfg.get("font_size", 64))
    primary_color = sub_cfg.get("primary_color", "&H00FFFFFF")
    outline_color = sub_cfg.get("outline_color", "&H00000000")
    outline_width = int(sub_cfg.get("outline_width", 4))

    margin_l = int(safe_cfg.get("subtitle_margin_l", 80))
    margin_r = int(safe_cfg.get("subtitle_margin_r", 180))
    margin_v = int(safe_cfg.get("subtitle_margin_v", 520))

    return f"""[Script Info]
Title: Edu Shorts Thai Subtitles
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 1
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},&H000000FF,{outline_color},&H80000000,-1,0,0,0,100,100,0,0,1,{outline_width},2,2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def run_subtitles(clip_dir: str | Path) -> Path:
    clip_path = resolve_clip_dir(clip_dir)
    script_file = clip_path / "script.json"
    manifest_file = clip_path / "audio" / "manifest.json"

    if not script_file.exists():
        raise FileNotFoundError(f"ไม่พบ {script_file}")
    if not manifest_file.exists():
        raise FileNotFoundError(f"ไม่พบ {manifest_file} กรุณารัน 04_tts.py ก่อน")

    script_data = json.loads(script_file.read_text(encoding="utf-8"))
    manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
    channel_cfg = load_yaml("channel.yaml")
    safe_cfg = load_yaml("safe_zones.yaml")

    sub_cfg = channel_cfg.get("subtitles", {})
    words_range = sub_cfg.get("words_per_chunk", [3, 6])
    min_w, max_w = int(words_range[0]), int(words_range[1])
    primary_color = sub_cfg.get("primary_color", "&H00FFFFFF")
    highlight_color = sub_cfg.get("highlight_color", "&H0000D7FF")
    do_highlight = bool(sub_cfg.get("highlight_keywords", True))

    scenes_by_id = {
        int(s.get("id", idx)): s
        for idx, s in enumerate(script_data.get("scenes", []), start=1)
    }

    ass_lines = [build_ass_header(channel_cfg, safe_cfg).rstrip()]
    event_count = 0

    for m_scene in manifest_data.get("scenes", []):
        sid = int(m_scene["scene_id"])
        scene_obj = scenes_by_id.get(sid, {})
        narration = scene_obj.get("narration") or m_scene.get("narration", "")
        emphasis_words = scene_obj.get("emphasis_words", [])

        start_sec = float(m_scene["start_sec"])
        end_sec = float(m_scene["end_sec"])
        scene_dur = max(0.2, end_sec - start_sec)

        tokens = tokenize_thai_words(narration)
        chunks = group_tokens_into_chunks(tokens, min_words=min_w, max_words=max_w)
        if not chunks:
            continue

        total_chars = sum(max(1, len(c)) for c in chunks)
        cursor = start_sec

        for idx, chunk in enumerate(chunks):
            if idx == len(chunks) - 1:
                c_end = end_sec
            else:
                ratio = max(1, len(chunk)) / total_chars
                c_end = min(end_sec, cursor + scene_dur * ratio)

            styled_text = (
                highlight_chunk_text(chunk, emphasis_words, primary_color, highlight_color)
                if do_highlight
                else chunk
            )
            ass_lines.append(
                f"Dialogue: 0,{format_ass_time(cursor)},{format_ass_time(c_end)},Default,,0,0,0,,{styled_text}"
            )
            cursor = c_end
            event_count += 1

    subs_path = clip_path / "subs.ass"
    subs_path.write_text("\n".join(ass_lines) + "\n", encoding="utf-8-sig")
    print(f"[06_subtitles] สร้างไฟล์ซับไตเติล {subs_path} ({event_count} บรรทัด)")
    return subs_path


def main() -> None:
    parser = argparse.ArgumentParser(description="06: สร้างซับไตเติลภาษาไทย subs.ass ด้วย PyThaiNLP")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    args = parser.parse_args()
    run_subtitles(args.clip)


if __name__ == "__main__":
    main()
