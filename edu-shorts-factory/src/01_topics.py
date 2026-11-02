from __future__ import annotations

import argparse
from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm import call_llm_json
from utils.paths import ensure_base_dirs, load_yaml, render_prompt, slugify
from utils.status import read_topics_csv, write_topics_csv


def pick_next_format(rows: list[dict[str, str]], formats: list[str]) -> str:
    recent = [r.get("format", "") for r in rows[-2:] if r.get("format")]
    if len(recent) == 2 and recent[0] == recent[1]:
        forbidden = recent[0]
        for fmt in formats:
            if fmt != forbidden:
                return fmt
    if rows:
        last_fmt = rows[-1].get("format", "")
        if last_fmt in formats:
            idx = (formats.index(last_fmt) + 1) % len(formats)
            return formats[idx]
    return formats[0] if formats else "why_question"


def run_topics(
    category: str | None = None,
    fmt: str | None = None,
    mock: bool = False,
) -> list[dict[str, str]]:
    ensure_base_dirs()
    formats_cfg = load_yaml("formats.yaml")
    available_formats = formats_cfg.get("formats", ["why_question"])
    categories = formats_cfg.get("default_categories", ["วิทยาศาสตร์ใกล้ตัว"])

    rows = read_topics_csv()
    chosen_category = category or categories[len(rows) % len(categories)]
    chosen_format = fmt or pick_next_format(rows, available_formats)
    existing_titles = [r.get("title", "") for r in rows]
    recent_formats = [r.get("format", "") for r in rows[-2:]]

    prompt = render_prompt(
        "01_topic.md",
        category=chosen_category,
        format=chosen_format,
        existing_topics=", ".join(existing_titles) if existing_titles else "ยังไม่มี",
        recent_formats=", ".join(recent_formats) if recent_formats else "ยังไม่มี",
    )

    mock_data = [
        {
            "title": "ทำไมน้ำแข็งถึงลอยน้ำ ทั้งที่ของแข็งทั่วไปจม",
            "slug": "why-ice-floats-on-water",
            "hook": "ของแข็งเกือบทุกชนิดจมเมื่ออยู่ในของเหลวเดิม แล้วทำไมน้ำแข็งถึงลอยน้ำ?",
            "category": chosen_category,
            "format": chosen_format,
            "why_interesting": "เห็นทุกวันในแก้วน้ำแต่อธิบายโครงสร้างผลึกน้ำแบบเข้าใจง่ายได้ใน 30 วินาที",
        },
        {
            "title": "ทำไมหั่นหัวหอมแล้วน้ำตาไหล",
            "slug": "why-onions-make-you-cry",
            "hook": "หั่นหัวหอมทีไรน้ำตาไหลทุกที หัวหอมปล่อยอะไรออกมาป้องกันตัวเอง?",
            "category": chosen_category,
            "format": chosen_format,
            "why_interesting": "เรื่องใกล้ตัวในครัวที่มีกลไกเคมีป้องกันตัวของพืชที่น่าทึ่ง",
        },
    ]

    generated = call_llm_json(prompt, mock_response=mock_data, force_mock=mock)
    next_id = max((int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()), default=0) + 1
    today_str = date.today().isoformat()

    added: list[dict[str, str]] = []
    for item in generated:
        title = item.get("title", "").strip()
        if not title or title in existing_titles:
            continue
        slug = slugify(item.get("slug") or title)
        new_row = {
            "id": str(next_id),
            "title": title,
            "slug": slug,
            "category": item.get("category") or chosen_category,
            "format": item.get("format") or chosen_format,
            "hook": item.get("hook", "").strip(),
            "status": "idea",
            "folder": "",
            "created_at": today_str,
        }
        rows.append(new_row)
        added.append(new_row)
        existing_titles.append(title)
        next_id += 1

    write_topics_csv(rows)
    print(f"[01_topics] เพิ่มหัวข้อใหม่ {len(added)} รายการ ลงใน data/topics.csv")
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="01: สร้างหัวข้อคลิปสั้นใหม่ลง data/topics.csv")
    parser.add_argument("--category", type=str, default=None, help="หมวดหมู่เนื้อหา")
    parser.add_argument("--format", type=str, default=None, help="รูปแบบคลิป (เช่น why_question)")
    parser.add_argument("--mock", action="store_true", help="ใช้ข้อมูลจำลองสำหรับทดสอบ")
    args = parser.parse_args()
    run_topics(category=args.category, fmt=args.format, mock=args.mock)


if __name__ == "__main__":
    main()
