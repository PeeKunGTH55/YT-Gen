from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm import call_llm_json
from utils.paths import (
    get_custom_rules_prompt,
    get_or_create_clip_dir,
    load_yaml,
    render_prompt,
    resolve_clip_dir,
)
from utils.status import read_topics_csv, update_status, write_topics_csv


def build_mock_hooks(title: str) -> dict[str, Any]:
    return {
        "variants": [
            {
                "pattern": "why_question",
                "hook": "แสงอาทิตย์เป็นสีขาว แล้วสีฟ้าบนท้องฟ้ามาจากไหน?",
            },
            {
                "pattern": "myth_vs_fact",
                "hook": "ท้องฟ้าไม่ได้มีสีฟ้าตั้งแต่แรก และไม่ได้สะท้อนสีน้ำทะเล",
            },
            {
                "pattern": "relatable_situation",
                "hook": "เคยสงสัยไหม ทำไมตอนเที่ยงฟ้าสีฟ้า แต่ตอนเย็นกลายเป็นสีส้ม?",
            },
            {
                "pattern": "verified_comparison",
                "hook": "คลื่นแสงสีฟ้าสั้นกว่าสีแดง จนชนโมเลกุลอากาศกระเจิงไปทั่วฟ้า",
            },
            {
                "pattern": "what_if",
                "hook": "ถ้าโลกไม่มีชั้นบรรยากาศ ตอนกลางวันท้องฟ้าจะเป็นสีดำสนิท",
            },
        ],
        "recommended_hook": "แสงอาทิตย์เป็นสีขาว แล้วสีฟ้าบนท้องฟ้ามาจากไหน?",
        "reason": "เชื่อมกับประโยคจบเพื่อวนลูปได้ทันที และตั้งคำถามจากสิ่งที่ทุกคนมองเห็นทุกวัน",
    }


def build_mock_script(title: str, fmt: str, hook: str) -> dict[str, Any]:
    return {
        "title": title,
        "format": fmt,
        "hook_used": hook,
        "scenes": [
            {
                "id": 1,
                "narration": "แสงอาทิตย์เป็นสีขาว แล้วสีฟ้าบนท้องฟ้ามาจากไหน?",
                "visual": "Nong Roo looking up curiously at a bright white sunbeam entering the sky",
                "emphasis_words": ["สีขาว", "สีฟ้า"],
                "claims": ["แสงอาทิตย์เป็นแสงขาวที่รวมแสงหลายสีเข้าด้วยกัน"],
            },
            {
                "id": 2,
                "narration": "ความจริงแล้ว แสงสีขาวซ่อนสีรุ้งทั้งเจ็ดสีไว้ข้างใน",
                "visual": "A glowing glass prism splitting a white light beam into seven colorful rainbow rays",
                "emphasis_words": ["แสงสีขาว", "เจ็ดสี"],
                "claims": ["แสงขาวจากดวงอาทิตย์ประกอบด้วยสเปกตรัมของแสงสีต่างๆ"],
            },
            {
                "id": 3,
                "narration": "ซึ่งแต่ละสีเดินทางเป็นคลื่นที่มีความยาวไม่เท่ากัน",
                "visual": "Comparison of long red light waves and short rapid blue light waves side by side",
                "emphasis_words": ["คลื่น", "ไม่เท่ากัน"],
                "claims": ["แสงแต่ละสีมีความยาวคลื่นแตกต่างกัน"],
            },
            {
                "id": 4,
                "narration": "แสงสีแดงเป็นคลื่นลูกยาว ส่วนแสงสีฟ้าเป็นคลื่นสั้นนิดเดียว",
                "visual": "Red wave taking big wide steps while blue wave takes tiny quick steps",
                "emphasis_words": ["สีแดง", "สีฟ้า", "คลื่นสั้น"],
                "claims": ["แสงสีแดงมีความยาวคลื่นมากกว่าแสงสีน้ำเงินและสีฟ้า"],
            },
            {
                "id": 5,
                "narration": "พอลำแสงพุ่งเข้าสู่ชั้นบรรยากาศโลกที่มีก๊าซอยู่เต็มไปหมด",
                "visual": "Earth surrounded by a soft atmosphere layer filled with tiny floating gas molecules",
                "emphasis_words": ["ชั้นบรรยากาศ", "ก๊าซ"],
                "claims": ["ชั้นบรรยากาศโลกประกอบด้วยโมเลกุลของก๊าซขนาดเล็กจำนวนมาก"],
            },
            {
                "id": 6,
                "narration": "ลองนึกถึงการกลิ้งลูกฟุตบอลกับลูกปิงปองผ่านสนามที่มีก้อนหินเล็กๆ",
                "visual": "A big soccer ball rolling straight over small pebbles while a tiny ping pong ball bounces everywhere",
                "emphasis_words": ["ลูกฟุตบอล", "ลูกปิงปอง"],
                "claims": ["การเปรียบเทียบขนาดคลื่นแสงกับการกระเจิงเมื่อชนสิ่งกีดขวางขนาดเล็ก"],
            },
            {
                "id": 7,
                "narration": "คลื่นยาวอย่างสีแดงจะข้ามผ่านไปง่าย แต่คลื่นสั้นอย่างสีฟ้าจะชนก๊าซแล้วกระเด็นกระจาย",
                "visual": "Blue light rays bouncing off tiny air molecules in all directions across the sky",
                "emphasis_words": ["สีฟ้า", "กระเด็นกระจาย"],
                "claims": ["การกระเจิงแบบเรย์ลีทำให้แสงคลื่นสั้นสีน้ำเงินและฟ้ากระเจิงได้ดีกว่าแสงสีแดง"],
            },
            {
                "id": 8,
                "narration": "แสงสีฟ้าจึงฟุ้งเต็มท้องฟ้าเข้าสู่ตาเราจากทุกทิศทาง",
                "visual": "Nong Roo smiling under a vibrant blue dome of scattered light rays",
                "emphasis_words": ["ฟุ้งเต็มท้องฟ้า", "ทุกทิศทาง"],
                "claims": ["เรามองเห็นท้องฟ้าเป็นสีฟ้าเพราะแสงสีฟ้ากระเจิงเข้าสู่ดวงตาจากทุกทิศทาง"],
            },
            {
                "id": 9,
                "narration": "ทั้งที่จุดเริ่มต้นที่พุ่งมาจากดวงอาทิตย์...",
                "visual": "View zooming back out toward the bright glowing sun in space emitting pure white light",
                "emphasis_words": ["จุดเริ่มต้น", "ดวงอาทิตย์"],
                "claims": [],
            },
        ],
        "loop_note": "ฉากที่ 9 จบด้วย 'ทั้งที่จุดเริ่มต้นที่พุ่งมาจากดวงอาทิตย์...' เชื่อมกลับเข้าฉากที่ 1 'แสงอาทิตย์เป็นสีขาว แล้วสีฟ้าบนท้องฟ้ามาจากไหน?' ได้ไร้รอยต่อ",
    }


def select_topic_row(topic_id: str | None, mock: bool = False) -> dict[str, str]:
    rows = read_topics_csv()

    if topic_id is not None:
        for r in rows:
            if str(r.get("id")) == str(topic_id):
                return r
        raise ValueError(f"ไม่พบ topic_id={topic_id} ใน data/topics.csv")

    channel_cfg = load_yaml("channel.yaml")
    topic_qc_enabled = bool(channel_cfg.get("qc", {}).get("topic_qc", {}).get("enabled", True))

    if topic_qc_enabled:
        import importlib
        mod_topic_qc = importlib.import_module("01_topic_qc_agent")
        approved_row, log = mod_topic_qc.get_next_approved_topic(mock=mock)
        return approved_row

    for r in rows:
        if r.get("status", "idea") == "idea":
            return r

    # หากหัวข้อที่สถานะเป็น idea หมดแล้ว ให้เรียก 01_topics คิดหัวข้อใหม่เพิ่มอัตโนมัติ
    print("[02_script] หัวข้อในคลังถูกใช้หมดแล้ว กำลังให้ AI คิดหัวข้อใหม่เพิ่มอัตโนมัติ...", flush=True)
    import importlib

    mod_01 = importlib.import_module("01_topics")
    mod_01.run_topics(mock=mock)
    rows = read_topics_csv()
    for r in rows:
        if r.get("status", "idea") == "idea":
            return r
    raise RuntimeError("ไม่สามารถสร้างหัวข้อใหม่ลง data/topics.csv ได้")


def run_script(
    topic_id: str | None = None,
    clip_dir: Path | None = None,
    mock: bool = False,
) -> Path:
    if clip_dir is not None:
        clip_dir = resolve_clip_dir(clip_dir)
        status_file = clip_dir / "status.json"
        if status_file.exists():
            st = json.loads(status_file.read_text(encoding="utf-8"))
            topic_id = str(st.get("topic_id", topic_id or "1"))

    row = select_topic_row(topic_id, mock=mock)
    tid = row["id"]
    title = row["title"]
    slug = row.get("slug") or f"topic-{tid}"
    fmt = row.get("format") or "why_question"
    initial_hook = row.get("hook") or title

    if clip_dir is None:
        existing_folder = row.get("folder", "").strip()
        if existing_folder:
            clip_dir = get_or_create_clip_dir(slug)
            clip_dir = clip_dir.parent / existing_folder
            clip_dir.mkdir(parents=True, exist_ok=True)
            (clip_dir / "audio").mkdir(parents=True, exist_ok=True)
            (clip_dir / "images").mkdir(parents=True, exist_ok=True)
        else:
            clip_dir = get_or_create_clip_dir(slug)

    # 1. Generate 5 hook variants via 06_hook_variants.md
    custom_rules = get_custom_rules_prompt()
    hook_prompt = render_prompt("06_hook_variants.md", title=title) + custom_rules
    hook_data = call_llm_json(
        hook_prompt,
        mock_response=build_mock_hooks(title),
        force_mock=mock,
    )
    (clip_dir / "hooks.json").write_text(
        json.dumps(hook_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    winning_hook = initial_hook
    if isinstance(hook_data, dict) and hook_data.get("recommended_hook"):
        winning_hook = hook_data["recommended_hook"]
    elif isinstance(hook_data, list) and hook_data:
        winning_hook = hook_data[0].get("hook", initial_hook)

    # 2. Generate script via 02_script.md
    script_prompt = (
        render_prompt(
            "02_script.md",
            title=title,
            format=fmt,
            hook=winning_hook,
        )
        + custom_rules
    )
    script_data = call_llm_json(
        script_prompt,
        mock_response=build_mock_script(title, fmt, winning_hook),
        force_mock=mock,
    )
    script_data.setdefault("title", title)
    script_data.setdefault("format", fmt)
    script_data["hook_used"] = winning_hook

    (clip_dir / "script.json").write_text(
        json.dumps(script_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Update topics.csv hook & folder
    rows = read_topics_csv()
    for r in rows:
        if str(r.get("id")) == str(tid):
            r["hook"] = winning_hook
            r["folder"] = clip_dir.name
            r["status"] = "scripted"
            break
    write_topics_csv(rows)

    update_status(
        clip_dir,
        "scripted",
        note=f"สร้างบท {len(script_data.get('scenes', []))} ฉาก พร้อมคัดเลือก Hook สำเร็จ",
        extra={"topic_id": tid, "title": title, "format": fmt},
    )
    print(f"[02_script] บันทึกบทลง {clip_dir / 'script.json'}")
    return clip_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="02: สร้างตัวเลือก Hook และเขียนบทลง script.json")
    parser.add_argument("--topic-id", type=str, default=None, help="รหัสหัวข้อใน data/topics.csv")
    parser.add_argument("--clip", type=str, default=None, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="ใช้โหมดจำลองข้อมูล")
    args = parser.parse_args()
    clip_path = Path(args.clip) if args.clip else None
    run_script(topic_id=args.topic_id, clip_dir=clip_path, mock=args.mock)


if __name__ == "__main__":
    main()
