"""กันบั๊ก: QC คืนหัวข้อเดิมซ้ำ 3 รอบ แล้วส่งการ์ดหัวข้อเดียวกัน 3 ใบเข้า Telegram

รัน: python tests/test_topic_qc_queue.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import utils.status as status  # noqa: E402
import importlib  # noqa: E402

HEADER = "id,title,slug,category,format,hook,status,folder,created_at\n"


def build_csv(tmp: Path, n: int = 5) -> None:
    lines = [HEADER]
    for i in range(1, n + 1):
        lines.append(f"{i},หัวข้อ {i},slug-{i},วิทยาศาสตร์ใกล้ตัว,why_question,hook {i},idea,,2026-11-10\n")
    (tmp / "topics.csv").write_text("".join(lines), encoding="utf-8")


def main() -> None:
    qc = importlib.import_module("01_topic_qc_agent")

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        build_csv(tmp)
        status.DATA_DIR = tmp
        qc.data_dir_hack = tmp  # ไม่ได้ใช้ แค่กัน lint

        batch = qc.get_approved_topics(count=3, mock=True)
        ids = [r["id"] for r in batch]
        assert len(ids) == 3, f"ต้องได้ 3 หัวข้อ ได้ {ids}"
        assert len(set(ids)) == 3, f"หัวข้อซ้ำ! ได้ {ids}"

        statuses = {r["id"]: r["status"] for r in status.read_topics_csv()}
        for tid in ids:
            assert statuses[tid] == "approved", f"หัวข้อ {tid} ต้องถูกจองสถานะ approved (ได้ {statuses[tid]})"

        again = [r["id"] for r in qc.get_approved_topics(count=3, mock=True)]
        assert again == ids, f"เรียกซ้ำต้องได้คิวเดิมก่อนผลิต (ได้ {again})"

        consumed = {tid: "scripted" for tid in ids}
        rows = status.read_topics_csv()
        for r in rows:
            r["status"] = consumed.get(r["id"], r["status"])
        status.write_topics_csv(rows)

        fresh = [r["id"] for r in qc.get_approved_topics(count=3, mock=True)]
        assert fresh == ["4", "5"], f"หลังผลิตแล้วต้องได้หัวข้อใหม่ที่เหลือ (ได้ {fresh})"

    print("OK — คิวหัวข้อไม่ซ้ำ และจองสถานะถูกต้อง")


if __name__ == "__main__":
    main()
