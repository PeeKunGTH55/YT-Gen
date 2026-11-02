from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.paths import resolve_clip_dir
from utils.status import read_status, read_topics_csv

mod_01 = importlib.import_module("01_topics")
mod_02 = importlib.import_module("02_script")
mod_03 = importlib.import_module("03_factcheck")
mod_04 = importlib.import_module("04_tts")
mod_05 = importlib.import_module("05_images")
mod_06 = importlib.import_module("06_subtitles")
mod_07 = importlib.import_module("07_render")
mod_08 = importlib.import_module("08_review")
mod_09 = importlib.import_module("09_publish")


def run_pipeline(
    *,
    topic_id: str | None = None,
    clip: str | None = None,
    auto: bool = False,
    mock: bool = False,
    approve_now: bool = False,
    publish: bool = False,
) -> Path:
    clip_path: Path | None = None

    if clip:
        clip_path = resolve_clip_dir(clip)
    else:
        rows = read_topics_csv()
        has_idea = any(r.get("status", "idea") == "idea" for r in rows)
        if not has_idea and topic_id is None:
            mod_01.run_topics(mock=mock)
        clip_path = mod_02.run_script(topic_id=topic_id, mock=mock)

    st = read_status(clip_path).get("status", "idea")

    if st in ("idea",):
        clip_path = mod_02.run_script(topic_id=topic_id, clip_dir=clip_path, mock=mock)
        st = "scripted"

    if st in ("scripted",):
        mod_03.run_factcheck(clip_path, mock=mock)
        st = "factchecked"

    if st in ("factchecked",):
        mod_04.run_tts(clip_path, mock=mock)
        mod_05.run_images(clip_path, mock=mock)
        st = "assets_ready"

    if st in ("assets_ready",):
        mod_06.run_subtitles(clip_path)
        mod_07.run_render(clip_path, mock=mock)
        st = "rendered"

    if st in ("rendered", "awaiting_approval"):
        st = mod_08.run_review(clip_path, approve_now=approve_now, mock=mock)

    if st == "approved" and (publish or approve_now or auto):
        mod_09.run_publish(clip_path, mock=mock)

    print(f"[pipeline] เสร็จสิ้นการทำงานที่โฟลเดอร์: {clip_path} (สถานะ: {read_status(clip_path).get('status')})")
    return clip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="รัน Pipeline ผลิตคลิปสั้นความรู้ครบวงจร")
    parser.add_argument("--topic-id", type=str, default=None, help="รหัสหัวข้อใน data/topics.csv")
    parser.add_argument("--clip", type=str, default=None, help="ระบุโฟลเดอร์คลิปเพื่อรันต่อจากสถานะเดิม")
    parser.add_argument("--auto", action="store_true", help="เลือกหัวข้อถัดไปอัตโนมัติ")
    parser.add_argument("--mock", action="store_true", help="รันโหมดทดสอบครบวงจรโดยไม่เสียค่า API")
    parser.add_argument("--approve-now", action="store_true", help="อนุมัติทันทีและรันไปจนถึงขั้น 09_publish")
    parser.add_argument("--publish", action="store_true", help="รันขั้น 09_publish เมื่อสถานะเป็น approved")
    args = parser.parse_args()

    run_pipeline(
        topic_id=args.topic_id,
        clip=args.clip,
        auto=args.auto,
        mock=args.mock,
        approve_now=args.approve_now,
        publish=args.publish,
    )


if __name__ == "__main__":
    main()
