from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import importlib
from utils.paths import load_yaml, resolve_clip_dir
from utils.status import read_status, update_status

mod_qc = importlib.import_module("08_qc_agent")


def send_telegram_qc_notification(
    clip_path: Path, bot_token: str, chat_id: str, qc_report: dict[str, Any]
) -> None:
    meta_file = clip_path / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
    yt_title = meta.get("youtube", {}).get("title", clip_path.name)
    score = qc_report.get("total_score", 0)

    text = (
        f"✅ [QC Subagent อนุมัติอัตโนมัติ]\n"
        f"📁 โฟลเดอร์: {clip_path.name}\n"
        f"🎬 ชื่อคลิป: {yt_title}\n"
        f"🏆 คะแนนคุณภาพ: {score}/100 (ผ่านเกณฑ์)\n"
        f"🚀 คลิปผ่านการตรวจสอบคุณภาพเรียบร้อย กำลังเข้าสู่ขั้นตอนเผยแพร่/ตั้งเวลาบน YouTube"
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    transport = httpx.HTTPTransport(local_address="0.0.0.0")
    try:
        with httpx.Client(transport=transport, timeout=30.0) as client:
            client.post(url, json={"chat_id": chat_id, "text": text})
    except Exception as e:
        print(f"[08_review] แจ้งเตือน Telegram ไม่สำเร็จ: {e}")


def send_telegram_review(
    clip_path: Path,
    bot_token: str,
    chat_id: str,
    qc_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_mp4 = clip_path / "final.mp4"
    meta_file = clip_path / "meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}

    yt_title = meta.get("youtube", {}).get("title", clip_path.name)
    yt_desc = meta.get("youtube", {}).get("description", "")

    if qc_report and not qc_report.get("passed", False):
        score = qc_report.get("total_score", 0)
        min_score = qc_report.get("min_pass_score", 85)
        violations_str = "\n".join(f"- ❌ {v}" for v in qc_report.get("violations", []))
        recomms_str = "\n".join(f"- 💡 {r}" for r in qc_report.get("recommendations", []))

        caption_text = (
            f"⚠️ [QC Subagent ตรวจไม่ผ่านเกณฑ์: {score}/{min_score}]\n"
            f"📁 โฟลเดอร์: {clip_path.name}\n"
            f"🎬 ชื่อคลิป: {yt_title}\n\n"
            f"📌 ข้อบกพร่องที่ตรวจพบ:\n{violations_str}\n"
        )
        if recomms_str:
            caption_text += f"\nคำแนะนำ:\n{recomms_str}\n"
        caption_text += "\n👉 ระบบส่งต่อให้คุณตัดสินใจ: กดปุ่มด้านล่างเพื่อ Approve หรือ Reject"
    else:
        caption_text = (
            f"[ตรวจอนุมัติ YouTube Shorts]\n"
            f"โฟลเดอร์: {clip_path.name}\n"
            f"ชื่อคลิป: {yt_title}\n\n"
            f"คำอธิบาย:\n{yt_desc}"
        )

    caption_text = caption_text[:1000]

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "Approve (อนุมัติโพสต์)", "callback_data": f"approve:{clip_path.name}"},
                {"text": "Reject (ระงับ/แก้ไข)", "callback_data": f"reject:{clip_path.name}"},
            ]
        ]
    }

    url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
    transport = httpx.HTTPTransport(local_address="0.0.0.0")
    with httpx.Client(transport=transport, timeout=120.0) as client:
        with final_mp4.open("rb") as vf:
            resp = client.post(
                url,
                data={
                    "chat_id": chat_id,
                    "caption": caption_text,
                    "reply_markup": json.dumps(reply_markup),
                },
                files={"video": (final_mp4.name, vf, "video/mp4")},
            )
            resp.raise_for_status()
            return resp.json()


def poll_telegram_decision(
    clip_path: Path,
    bot_token: str,
    wait_seconds: int = 0,
) -> str | None:
    target_approve = f"approve:{clip_path.name}"
    target_reject = f"reject:{clip_path.name}"
    deadline = time.time() + max(0, wait_seconds)
    offset = 0

    transport = httpx.HTTPTransport(local_address="0.0.0.0")
    with httpx.Client(transport=transport, timeout=35.0) as client:
        while True:
            resp = client.get(
                f"https://api.telegram.org/bot{bot_token}/getUpdates",
                params={"offset": offset, "timeout": 10 if wait_seconds > 0 else 0},
            )
            resp.raise_for_status()
            updates = resp.json().get("result", [])

            for upd in updates:
                offset = max(offset, int(upd["update_id"]) + 1)
                cb = upd.get("callback_query", {})
                data = cb.get("data", "")
                cb_id = cb.get("id")

                if data in (target_approve, target_reject):
                    decision = "approved" if data == target_approve else "rejected"
                    if cb_id:
                        client.post(
                            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                            json={"callback_query_id": cb_id, "text": f"บันทึกสถานะ: {decision}"},
                        )
                    update_status(
                        clip_path,
                        decision,
                        note=f"ผลอนุมัติจาก Telegram: {decision}",
                    )
                    return decision

            if time.time() >= deadline:
                break
            time.sleep(2)

    return None


def run_review(
    clip_dir: str | Path,
    *,
    check_only: bool = False,
    wait_seconds: int = 0,
    approve_now: bool = False,
    mock: bool = False,
) -> str:
    clip_path = resolve_clip_dir(clip_dir)
    channel_cfg = load_yaml("channel.yaml")
    qc_cfg = channel_cfg.get("qc", {})
    qc_enabled = bool(qc_cfg.get("enabled", True))
    require_approval = bool(channel_cfg.get("workflow", {}).get("require_approval", True))

    if approve_now:
        update_status(
            clip_path,
            "approved",
            note="อนุมัติทันที (สั่งผ่าน --approve-now)",
        )
        print(f"[08_review] อนุมัติคลิป {clip_path.name} เรียบร้อย (status=approved)")
        return "approved"

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    # -------------------------------------------------------------
    # 1. Run Autonomous QC Critic Subagent
    # -------------------------------------------------------------
    qc_report: dict[str, Any] | None = None
    if qc_enabled:
        decision, qc_report = mod_qc.run_qc_review(clip_path, mock=mock)
        if decision == "approved":
            # Auto-approved by QC Subagent!
            if bot_token and chat_id and not mock:
                send_telegram_qc_notification(clip_path, bot_token, chat_id, qc_report)
            print(f"[08_review] QC ผ่านเกณฑ์ ({qc_report.get('total_score', 0)}/100) -> อนุมัติอัตโนมัติเรียบร้อย")
            return "approved"

    # If QC disabled and require_approval is false
    if not qc_enabled and not require_approval:
        update_status(
            clip_path,
            "approved",
            note="อนุมัติอัตโนมัติ (require_approval=false)",
        )
        return "approved"

    # -------------------------------------------------------------
    # 2. Fallback to Telegram (Option 1A) when QC fails or manual
    # -------------------------------------------------------------
    if mock or not bot_token or not chat_id:
        update_status(
            clip_path,
            "awaiting_approval",
            note="รออนุมัติ (โหมดทดสอบหรือยังไม่ได้ตั้งค่า TELEGRAM_BOT_TOKEN)",
        )
        print(
            f"[08_review] บันทึกสถานะ awaiting_approval สำหรับ {clip_path.name} "
            "(รันพร้อม --approve-now เพื่อจำลองการกดอนุมัติ)"
        )
        return "awaiting_approval"

    if not check_only:
        send_telegram_review(clip_path, bot_token, chat_id, qc_report=qc_report)
        update_status(
            clip_path,
            "awaiting_approval",
            note="ส่งคลิปและรายงาน QC เข้า Telegram เพื่อรอการตัดสินใจแล้ว",
        )
        print(f"[08_review] ส่งคลิปและรายงาน QC ของ {clip_path.name} เข้า Telegram (@sorap_yt_gen_bot) แล้ว")

    if check_only or wait_seconds > 0:
        decision = poll_telegram_decision(clip_path, bot_token, wait_seconds=wait_seconds)
        if decision:
            print(f"[08_review] ได้รับผลจาก Telegram: {decision}")
            return decision

    return read_status(clip_path).get("status", "awaiting_approval")


def main() -> None:
    parser = argparse.ArgumentParser(description="08: ตรวจสอบคุณภาพคลิปด้วย QC Subagent และส่ง Telegram")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--check", action="store_true", help="เช็กผลการกดปุ่มจาก Telegram โดยไม่ส่งคลิปซ้ำ")
    parser.add_argument("--wait", type=int, default=0, help="รอรับผลกดปุ่มจาก Telegram (ระบุจำนวนวินาที)")
    parser.add_argument("--approve-now", action="store_true", help="อนุมัติคลิปทันทีผ่าน CLI")
    parser.add_argument("--mock", action="store_true", help="โหมดทดสอบไม่เรียก Telegram API")
    args = parser.parse_args()

    run_review(
        args.clip,
        check_only=args.check,
        wait_seconds=args.wait,
        approve_now=args.approve_now,
        mock=args.mock,
    )


if __name__ == "__main__":
    main()
