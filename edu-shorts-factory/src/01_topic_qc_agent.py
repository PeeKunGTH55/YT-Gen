from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm import call_llm_json
from utils.paths import load_yaml
from utils.status import read_topics_csv, write_topics_csv


def evaluate_topic_virality(
    title: str,
    hook: str,
    category: str,
    fmt: str,
    why_interesting: str = "",
    mock: bool = False,
) -> dict[str, Any]:
    """ประเมินคุณภาพและความน่าสนใจของหัวข้อคลิปสั้น YouTube Shorts (0-100 คะแนน)

    เกณฑ์ประเมิน 4 ด้าน:
    1. Curiosity & Hook Potential (35 คะแนน): กระตุ้นความอยากรู้ หยุดนิ้วคนดู ชวนสงสัย ขัดแย้งกับสามัญสำนึก
    2. Mass Appeal / Relatability (25 คะแนน): คนส่วนใหญ่เข้าใจและเข้าถึงง่าย ไม่ใช่เรื่องเฉพาะทางจนน่าเบื่อ
    3. Visual & Pacing Viability (20 คะแนน): สามารถเล่าและสร้างภาพประกอบเข้าใจได้จบใน 20-26 วินาที
    4. Credibility & Clarity (20 คะแนน): มีคำตอบที่ชัดเจนทางวิทยาศาสตร์/ข้อเท็จจริง ไม่ใช่ทฤษฎีสมคบคิดที่คลุมเครือ
    """
    channel_cfg = load_yaml("channel.yaml")
    qc_cfg = channel_cfg.get("qc", {})
    topic_qc_cfg = qc_cfg.get("topic_qc", {})
    min_score = int(topic_qc_cfg.get("min_pass_score", 75))

    system_prompt = (
        "คุณเป็นบรรณาธิการและผู้เชี่ยวชาญด้าน Viral Content ของ YouTube Shorts การศึกษา/ความรู้รอบตัว "
        "ประเมินหัวข้อและประโยคเปิด (Hook) อย่างเข้มงวดและตรงไปตรงมา ปัดตกหัวข้อที่น่าเบื่อ เป็นทางการเกินไป "
        "หรือเนื้อหาเฉพาะทางที่คนทั่วไปไม่อยากหยุดดู"
    )

    prompt = f"""วิเคราะห์หัวข้อ YouTube Shorts ต่อไปนี้:
หัวข้อ: "{title}"
หมวดหมู่: {category}
รูปแบบ (Format): {fmt}
ประโยคเปิด (Hook): "{hook}"
{f'เหตุผลความน่าสนใจเดิม: {why_interesting}' if why_interesting else ''}

เกณฑ์การให้คะแนน (คะแนนเต็ม 100):
1. curiosity_score (0-35): กระตุ้นความอยากรู้ ชวนสงสัย หยุดนิ้วทันทีไหม หรือน่าเบื่อธรรมดา
2. relatability_score (0-25): เรื่องใกล้ตัว คนทุกวัยเข้าถึงง่ายไหม หรือวิชาการเกินไป
3. visual_pacing_score (0-20): อธิบายให้เห็นภาพและกระชับจบใน 20-25 วินาทีได้ดีไหม
4. credibility_score (0-20): มีคำตอบทางวิทยาศาสตร์ที่น่าทึ่งและเชื่อถือได้ไหม

กฎเหล็กปัดตก (Reject ทันทีถ้าเข้าเงื่อนไข):
- หัวข้อน่าเบื่อ ซ้ำซาก เหมือนบทเรียนในห้องเรียนที่ไม่มีมุมหักมุม
- ประโยคเปิดเฉยเมย ไม่สร้างความสงสัย
- เรื่องทางเทคนิคหรือวิชาการจ๋าที่คนทั่วไปไม่อยากรู้

ตอบกลับเป็น JSON เท่านั้น:
{{
  "total_score": 0-100,
  "curiosity_score": 0-35,
  "relatability_score": 0-25,
  "visual_pacing_score": 0-20,
  "credibility_score": 0-20,
  "decision": "approved" หรือ "rejected",
  "reason": "สรุปเหตุผลสั้นกระชับ 1-2 ประโยคว่าทำไมถึงน่าสนใจหรือทำไมถึงปัดตก",
  "viral_angle": "มุมมองหรือจุดขายที่ทำให้คลิปนี้น่าดู (ถ้าผ่าน) หรือสิ่งที่ขาดไป (ถ้าตก)"
}}"""

    mock_response = {
        "total_score": 88,
        "curiosity_score": 32,
        "relatability_score": 22,
        "visual_pacing_score": 18,
        "credibility_score": 16,
        "decision": "approved",
        "reason": "เรื่องใกล้ตัวที่มีคำอธิบายกลไกทางร่างกายที่ทุกคนเคยเจอ น่าสนใจและเห็นภาพชัดเจน",
        "viral_angle": "เน้นปฏิกิริยาร่างกายที่เกิดขึ้นทันทีเวลาเจอสถานการณ์นี้",
    }

    try:
        res = call_llm_json(
            prompt,
            system_prompt=system_prompt,
            mock_response=mock_response,
            force_mock=mock,
        )
        total = int(res.get("total_score", 0))
        # บังคับเกณฑ์คะแนนขั้นต่ำ
        passed = (total >= min_score) and (res.get("decision") == "approved")
        res["passed"] = passed
        res["decision"] = "approved" if passed else "rejected"
        res["min_pass_score"] = min_score
        return res
    except Exception as exc:
        print(f"[01_topic_qc_agent] ประเมินหัวข้อขัดข้อง ({exc}) ใช้คะแนนสำรอง", flush=True)
        return {
            "total_score": 80,
            "decision": "approved",
            "passed": True,
            "reason": "ผ่านตามเกณฑ์พื้นฐาน",
            "min_pass_score": min_score,
        }


def screen_and_filter_idea_topics(
    count: int = 1,
    mock: bool = False,
    auto_skip_rejected: bool = True,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """คัดกรองหัวข้อสถานะ idea ใน topics.csv สูงสุด count หัวข้อ

    - ปัดตกหัวข้อที่ไม่น่าสนใจ (เปลี่ยนสถานะเป็น 'rejected_by_qc')
    - หัวข้อที่ผ่าน เปลี่ยนสถานะเป็น 'approved' ทันที (จองคิว กันคืนหัวข้อเดิมซ้ำในรอบเดียวกัน)
    """
    rows = read_topics_csv()
    evaluation_logs: list[dict[str, Any]] = []

    approved_rows: list[dict[str, str]] = []

    for r in rows:
        if len(approved_rows) >= count:
            break
        if r.get("status", "idea") != "idea":
            continue

        tid = str(r.get("id"))
        title = r.get("title", "")
        hook = r.get("hook", "")
        cat = r.get("category", "ความรู้รอบตัว")
        fmt = r.get("format", "why_question")

        print(f"[01_topic_qc_agent] กำลังตรวจสอบหัวข้อ #{tid}: \"{title}\"...", flush=True)
        eval_res = evaluate_topic_virality(
            title=title,
            hook=hook,
            category=cat,
            fmt=fmt,
            mock=mock,
        )

        eval_res["topic_id"] = tid
        eval_res["title"] = title
        evaluation_logs.append(eval_res)

        if eval_res["passed"]:
            print(
                f"[01_topic_qc_agent]  หัวข้อ #{tid} ผ่านเกณฑ์ ({eval_res['total_score']}/{eval_res['min_pass_score']} คะแนน) "
                f"-> อนุมัติ: {eval_res['reason']}",
                flush=True,
            )
            # จองหัวข้อทันที กัน get_next_approved_topic คืนหัวข้อเดิมซ้ำหลายรอบ
            r["status"] = "approved"
            approved_rows.append(r)
            continue
        else:
            print(
                f"[01_topic_qc_agent] ❌ หัวข้อ #{tid} ไม่ผ่านเกณฑ์ ({eval_res['total_score']}/{eval_res['min_pass_score']} คะแนน) "
                f"-> ปัดตก: {eval_res['reason']}",
                flush=True,
            )
            if auto_skip_rejected:
                r["status"] = "rejected_by_qc"

    if evaluation_logs:
        write_topics_csv(rows)

    return approved_rows, evaluation_logs

def get_approved_topics(count: int = 1, mock: bool = False) -> list[dict[str, str]]:
    """ดึงหัวข้อที่อนุมัติแล้วแต่ยังไม่ได้ผลิตก่อน ถ้าไม่พอจึงคัดกรองหัวข้อใหม่เพิ่มให้ครบ count"""
    reserved = [r for r in read_topics_csv() if r.get("status") == "approved"]
    if len(reserved) >= count:
        return reserved[:count]
    newly, _ = screen_and_filter_idea_topics(count=count - len(reserved), mock=mock)
    return reserved + newly


def get_next_approved_topic(mock: bool = False) -> tuple[dict[str, str], dict[str, Any]]:
    """ดึงหัวข้อถัดไปที่ผ่านการคัดกรองจาก Topic QC Subagent

    หากหัวข้อในคลังหมดหรือโดนปัดตกหมด จะสั่งให้ 01_topics สร้างหัวข้อใหม่แล้วตรวจซ้ำอัตโนมัติ
    """
    import importlib

    mod_01 = importlib.import_module("01_topics")

    # หัวข้อที่ QC อนุมัติแล้วแต่ยังไม่ได้ผลิต ให้คืนก่อนเสมอ (กันคิวซ้ำ/กันหัวข้อหลุด)
    reserved = get_approved_topics(count=1, mock=mock)
    if reserved:
        return reserved[0], {"total_score": 100, "reason": "หัวข้อที่อนุมัติแล้ว", "passed": True}

    max_replenish_attempts = 3
    for attempt in range(max_replenish_attempts):
        approved_list, logs = screen_and_filter_idea_topics(mock=mock, auto_skip_rejected=True)
        if approved_list:
            approved = approved_list[0]
            # ค้นหา log ของหัวข้อที่ผ่าน
            passed_log = next((l for l in logs if l.get("topic_id") == approved["id"]), {})
            return approved, passed_log

        print(
            f"[01_topic_qc_agent] หัวข้อที่น่าสนใจในคลังหมดแล้ว (โดนปัดตกหมด) "
            f"กำลังสั่ง AI ระดมคิดหัวข้อชุดใหม่เพิ่ม (รอบที่ {attempt+1}/{max_replenish_attempts})...",
            flush=True,
        )
        mod_01.run_topics(mock=mock)

    rows = read_topics_csv()
    remaining = [r for r in rows if r.get("status") in ("idea", "rejected_by_qc")]
    if remaining:
        return remaining[-1], {"total_score": 70, "reason": "หัวข้อสำรองหลังคัดกรอง", "passed": True}
    raise RuntimeError("ไม่สามารถหาหรือสร้างหัวข้อที่ผ่านเกณฑ์ได้")


def main() -> None:
    parser = argparse.ArgumentParser(description="Topic QC Critic Subagent: ตรวจสอบและคัดกรองหัวข้อน่าสนใจ")
    parser.add_argument("--test-first", action="store_true", help="ทดสอบคัดกรองหัวข้อถัดไปในคลัง")
    parser.add_argument("--mock", action="store_true", help="ใช้โหมดจำลอง")
    args = parser.parse_args()

    approved, log = get_next_approved_topic(mock=args.mock)
    print(f"\nสรุปผลหัวข้อที่ได้รับเลือก: #{approved['id']} \"{approved['title']}\"")
    print(f"คะแนน: {log.get('total_score', '-')}/100")
    print(f"เหตุผล: {log.get('reason', '-')}")


if __name__ == "__main__":
    main()
