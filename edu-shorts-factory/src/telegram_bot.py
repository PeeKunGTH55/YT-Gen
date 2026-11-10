from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import date, datetime
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "src"))
load_dotenv(ROOT_DIR / ".env")

from utils.llm import call_llm_json
from utils.paths import (
    LOGS_DIR,
    OUTPUT_DIR,
    add_custom_rule,
    ensure_base_dirs,
    get_custom_rules_prompt,
    load_custom_rules,
    load_yaml,
    slugify,
)
from utils.status import read_status, read_topics_csv, update_status, write_topics_csv

mod_01 = importlib.import_module("01_topics")
mod_topic_qc = importlib.import_module("01_topic_qc_agent")
mod_02 = importlib.import_module("02_script")
mod_03 = importlib.import_module("03_factcheck")
mod_04 = importlib.import_module("04_tts")
mod_05 = importlib.import_module("05_images")
mod_06 = importlib.import_module("06_subtitles")
mod_07 = importlib.import_module("07_render")
mod_08 = importlib.import_module("08_review")
mod_09 = importlib.import_module("09_publish")

AVAILABLE_VOICES = {
    "bualoi": "หญิง - เสียงใสโทนสูง สดใส คมชัด (9/10)",
    "mooping": "ชาย - โทนขี้เล่น สดใส กระฉับกระเฉง (8/10)",
    "tomyum": "หญิง - โทนใส นุ่มนวล ฟังสบาย (7/10)",
    "khaoniao": "ชาย - โทนสุขุม นิ่ง จังหวะคงที่ (6/10)",
    "tubtimkrob": "หญิง - โทนอบอุ่น นุ่มลึก (5/10)",
    "krongkraeng": "ชาย - โทนทุ้มต่ำ ขรึม (4/10)",
    "panang": "ชาย - โทนทุ้มลึก กังวาน (3/10)",
}

CHAT_HISTORY: list[dict[str, str]] = []
_GEN_LOCK = threading.Lock()
_GEN_RUNNING: set[str] = set()


def ensure_single_instance() -> None:
    """ป้องกันการรัน telegram_bot.py ซ้ำซ้อนจนเกิด 409 Conflict"""
    ensure_base_dirs()
    pid_file = LOGS_DIR / "telegram_bot.pid"
    my_pid = os.getpid()
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text(encoding="utf-8").strip())
            if old_pid != my_pid:
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(old_pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(1)
        except Exception:
            pass
    pid_file.write_text(str(my_pid), encoding="utf-8")


def tg_client() -> httpx.Client:
    transport = httpx.HTTPTransport(local_address="0.0.0.0")
    return httpx.Client(transport=transport, timeout=60.0)


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> None:
    body: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        body["reply_markup"] = reply_markup
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    with tg_client() as client:
        r = client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            content=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        if r.status_code != 200:
            # ไม่ raise แต่ต้องเห็นในคอนโซล (สาเหตุกดอนุมัติแล้วเงียบ)
            print(
                f"[telegram_bot] sendMessage ล้มเหลว: {r.status_code} {r.text[:300]}",
                flush=True,
            )


def get_latest_clip_dir() -> Path | None:
    if not OUTPUT_DIR.exists():
        return None
    dirs = [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and (d / "script.json").exists()]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.stat().st_mtime)


def build_channel_context() -> str:
    latest = get_latest_clip_dir()
    topics = read_topics_csv()
    topics_summary = [
        f"[{r.get('id')}] {r.get('title')} (status={r.get('status')})"
        for r in topics[-8:]
    ]

    latest_info: dict[str, Any] = {}
    if latest:
        st = read_status(latest)
        script_file = latest / "script.json"
        script_data = (
            json.loads(script_file.read_text(encoding="utf-8"))
            if script_file.exists()
            else {}
        )
        latest_info = {
            "folder": latest.name,
            "status": st.get("status"),
            "title": script_data.get("title"),
            "scenes": [
                {"id": s.get("id"), "narration": s.get("narration")}
                for s in script_data.get("scenes", [])
            ],
        }

    channel_cfg = load_yaml("channel.yaml")
    daily_sched = channel_cfg.get("workflow", {}).get("daily_schedule", {})

    return json.dumps(
        {
            "current_voice": os.getenv("TOKENME_VOICE", "bualoi"),
            "available_voices": AVAILABLE_VOICES,
            "global_custom_rules": load_custom_rules(),
            "daily_schedule": daily_sched,
            "topics_in_queue": topics_summary,
            "latest_clip": latest_info,
        },
        ensure_ascii=False,
        indent=2,
    )


def converse_and_route(user_text: str) -> dict[str, Any]:
    context_str = build_channel_context()
    recent_turns = "\n".join(f"{m['role']}: {m['text']}" for m in CHAT_HISTORY[-8:])

    prompt = f"""คุณคือ AI Producer ประจำช่อง YouTube Shorts ความรู้ภาษาไทย คุยกับเจ้าของช่องใน Telegram

ข้อมูลสถานะระบบปัจจุบัน:
{context_str}

ประวัติการสนทนาล่าสุด:
{recent_turns}

ข้อความล่าสุดจากเจ้าของช่อง:
"{user_text}"

กฎเหล็กของ Telegram Bot:
1. ถ้าเจ้าของช่องถามคำถาม พูดคุย หรือปรึกษาทั่วไป ให้ตอบอย่างเดียว ("action": "none") ห้ามสั่งทำคลิปเองเด็ดขาด
2. ถ้าเจ้าของช่องสั่งให้สร้างคลิป (เช่น "ทำคลิปเรื่อง...", "ทำคลิปถัดไป", "สร้างคลิป...") ให้ตั้ง:
   - "action": "propose_custom_topic" (กรณีระบุหัวข้อเอง) พร้อมระบุ topic_title, slug, hook
   - หรือ "action": "propose_next_topic" (กรณีสั่งทำคลิปถัดไปจากคลัง)
   โดยระบบจะส่งหัวข้อไปให้เจ้าของช่องกดปุ่มอนุมัติหัวข้อก่อนเสมอ จะยังไม่สร้างคลิปทันที
3. ถ้าสั่งเปลี่ยนเสียงพากย์คลิปล่าสุด ตั้ง "action": "change_voice"
4. ถ้าสั่งแก้บทคลิปล่าสุด ตั้ง "action": "edit_script"
5. ถ้าสั่งคิดหัวข้อเข้าคลังเฉยๆ ตั้ง "action": "generate_ideas"

ตอบเป็น JSON เท่านั้น:
{{
  "reply": "ข้อความตอบกลับสั้นกระชับ (กรณี propose_custom_topic หรือ propose_next_topic ให้ปล่อยว่าง '' เพราะระบบจะส่งการ์ดหัวข้อพร้อมปุ่มอนุมัติแทน)",
  "action": "none | propose_custom_topic | propose_next_topic | change_voice | edit_script | generate_ideas",
  "topic_title": "ชื่อหัวข้อภาษาไทย (เฉพาะเมื่อ action=propose_custom_topic)",
  "slug": "english-kebab-slug (เฉพาะเมื่อ action=propose_custom_topic)",
  "hook": "ประโยคเปิดแนว 'คุณเคยสงสัยไหม...' (เฉพาะเมื่อ action=propose_custom_topic)",
  "voice": "ชื่อเสียงพากย์จาก available_voices (เฉพาะเมื่อ action=change_voice)",
  "edit_instruction": "รายละเอียดการแก้บท (เฉพาะเมื่อ action=edit_script)",
  "category": "หมวดหมู่ (เฉพาะเมื่อ action=generate_ideas)"
}}"""

    res = call_llm_json(
        prompt,
        mock_response={"reply": "รับทราบครับ", "action": "none"},
    )
    CHAT_HISTORY.append({"role": "user", "text": user_text})
    if res.get("reply"):
        CHAT_HISTORY.append({"role": "assistant", "text": res.get("reply", "")})
    return res


def send_topic_proposal(
    bot_token: str,
    chat_id: str,
    row: dict[str, str],
    is_daily: bool = False,
    daily_index: str = "",
) -> None:
    tid = row["id"]
    title = row["title"]
    cat = row.get("category", "ความรู้รอบตัว")
    fmt = row.get("format", "why_question")
    hook = row.get("hook") or f"คุณเคยสงสัยไหม {title}?"

    idx_label = f" ({daily_index})" if daily_index else ""
    header = f"[ขออนุมัติหัวข้อคลิปประจำวัน{idx_label}]" if is_daily else "[ขออนุมัติหัวข้อก่อนสร้างคลิป]"
    text = (
        f"{header}\n"
        f"รหัสหัวข้อ: #{tid}\n"
        f"หัวข้อ: {title}\n"
        f"หมวดหมู่: {cat} ({fmt})\n"
        f"ประโยคเปิด (Hook): {hook}\n\n"
        f"ต้องการให้สร้างคลิปหัวข้อนี้เลยไหมครับ?"
    )
    markup = {
        "inline_keyboard": [
            [
                {
                    "text": "อนุมัติหัวข้อ (เริ่มสร้างคลิป)",
                    "callback_data": f"start_topic:{tid}",
                },
                {
                    "text": "เปลี่ยนหัวข้อถัดไป",
                    "callback_data": f"skip_topic:{tid}",
                },
            ]
        ]
    }
    send_message(bot_token, chat_id, text, reply_markup=markup)


def get_or_replenish_idea_topics(count: int = 1) -> list[dict[str, str]]:
    channel_cfg = load_yaml("channel.yaml")
    topic_qc_enabled = bool(channel_cfg.get("qc", {}).get("topic_qc", {}).get("enabled", True))

    approved_list: list[dict[str, str]] = []
    if topic_qc_enabled:
        try:
            approved_list = mod_topic_qc.get_approved_topics(count=count)
        except Exception as e:
            print(f"[telegram_bot] Topic QC error: {e}", flush=True)
        if approved_list:
            return approved_list  # ได้ไม่ครบ count ก็คืนเท่าที่ QC อนุมัติ (ห้ามส่งหัวข้อที่ยังไม่ตรวจ)

    rows = read_topics_csv()
    available = [r for r in rows if r.get("status", "idea") == "idea"]
    if len(available) < count:
        mod_01.run_topics()
        rows = read_topics_csv()
        available = [r for r in rows if r.get("status", "idea") == "idea"]
    return available[:count]


def get_or_replenish_next_idea_topic() -> dict[str, str]:
    channel_cfg = load_yaml("channel.yaml")
    topic_qc_enabled = bool(channel_cfg.get("qc", {}).get("topic_qc", {}).get("enabled", True))
    if topic_qc_enabled:
        approved, _ = mod_topic_qc.get_next_approved_topic()
        return approved

    topics = get_or_replenish_idea_topics(count=1)
    if topics:
        return topics[0]
    raise RuntimeError("ไม่สามารถดึงหัวข้อใหม่จากคลังได้")


def daily_schedule_worker(bot_token: str, chat_id: str) -> None:
    last_sent_date = ""
    while True:
        try:
            channel_cfg = load_yaml("channel.yaml")
            sched = channel_cfg.get("workflow", {}).get("daily_schedule", {})
            enabled = bool(sched.get("enabled", True))
            sched_time = str(sched.get("time", "10:00")).strip()
            batch_count = int(sched.get("batch_count", 3))
            mode = str(sched.get("mode", "topic_approval")).strip()

            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            now_hhmm = now.strftime("%H:%M")

            if enabled and now_hhmm == sched_time and last_sent_date != today_str:
                last_sent_date = today_str
                print(
                    f"[daily_schedule] ถึงเวลา {sched_time} น. ส่ง {batch_count} หัวข้อประจำวันเข้า Telegram...",
                    flush=True,
                )
                topics = get_or_replenish_idea_topics(count=batch_count)
                if mode == "clip_approval":
                    send_message(
                        bot_token,
                        chat_id,
                        f"[แจ้งเตือนเวลา {sched_time} น.] ถึงเวลาผลิตคลิปประจำวัน (ทั้งหมด {len(topics)} คลิป) กำลังสร้างคลิปตามลำดับครับ...",
                    )
                    for r in topics:
                        run_full_generation_for_topic(bot_token, chat_id, r["id"])
                        time.sleep(1)
                else:
                    send_message(
                        bot_token,
                        chat_id,
                        f"[แจ้งเตือนเวลา {sched_time} น.] ถึงเวลาอนุมัติคลิปประจำวัน (เป้าหมาย {len(topics)} คลิป)\n"
                        f"กรุณาตรวจสอบและกดอนุมัติหัวข้อที่ต้องการสร้างคลิปด้านล่างนี้ได้เลยครับ:",
                    )
                    for idx, r in enumerate(topics, start=1):
                        send_topic_proposal(
                            bot_token,
                            chat_id,
                            r,
                            is_daily=True,
                            daily_index=f"{idx}/{len(topics)}",
                        )
                        time.sleep(0.5)
        except Exception as exc:
            print(f"[daily_schedule] ขัดข้อง: {exc}", flush=True)
        time.sleep(25)


def start_generation_async(bot_token: str, chat_id: str, topic_id: str) -> None:
    """รัน pipeline ใน thread แยก กัน loop polling ค้าง + กันกดซ้ำหัวข้อเดียวกันซ้ำซ้อน"""
    tid = str(topic_id)
    with _GEN_LOCK:
        if tid in _GEN_RUNNING:
            send_message(bot_token, chat_id, f"หัวข้อ #{tid} กำลังผลิตอยู่แล้วครับ รออีกสักครู่นะครับ")
            return
        _GEN_RUNNING.add(tid)

    def _worker() -> None:
        try:
            run_full_generation_for_topic(bot_token, chat_id, tid)
        finally:
            with _GEN_LOCK:
                _GEN_RUNNING.discard(tid)

    threading.Thread(target=_worker, daemon=True).start()

def run_full_generation_for_topic(bot_token: str, chat_id: str, topic_id: str) -> None:
    rows = read_topics_csv()
    target = next((r for r in rows if str(r.get("id")) == str(topic_id)), None)
    title = target["title"] if target else f"#{topic_id}"

    # ส่งแจ้งแค่ข้อความเดียวตอนเริ่ม ไม่ส่ง 1/5..5/5 ให้รกแชต
    send_message(
        bot_token,
        chat_id,
        f"รับการอนุมัติหัวข้อ \"{title}\" กำลังผลิตคลิปจนเสร็จ (เสร็จแล้วจะส่งวิดีโอพร้อมปุ่มอนุมัติโพสต์ให้ทันทีครับ)...",
    )
    try:
        clip_path = mod_02.run_script(topic_id=str(topic_id))
        mod_03.run_factcheck(clip_path)
        mod_04.run_tts(clip_path)
        mod_05.run_images(clip_path)
        mod_06.run_subtitles(clip_path)
        mod_07.run_render(clip_path)
        review_st = mod_08.run_review(clip_path)
        if review_st == "approved":
            res = mod_09.run_publish(clip_path)
            success_msg = f"🎉 [QC ตรวจผ่านฉลุย] เผยแพร่/ตั้งเวลาสำเร็จ!\nลิงก์: {res.get('youtube_url', '')}"
            if res.get("scheduled_at"):
                success_msg += f"\n⏰ กำหนดปล่อย: {res['scheduled_at']}"
            send_message(bot_token, chat_id, success_msg)
    except Exception as exc:
        traceback.print_exc()
        send_message(
            bot_token,
            chat_id,
            f"❌ เกิดข้อผิดพลาดขณะผลิตคลิป \"{title}\":\n{exc}\n\n👉 ระบบบันทึกไฟล์ที่เสร็จแล้วไว้ สามารถกดลองต่อได้ครับ",
        )


def handle_callback(
    bot_token: str, chat_id: str, callback_id: str, data: str
) -> None:
    action, value = data.split(":", 1)

    with tg_client() as client:
        client.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": f"รับคำสั่ง: {action}"},
        )

    # 1. กดอนุมัติหัวข้อ -> เริ่มสร้างคลิปจริง (ทำใน thread เพื่อให้บอทยังตอบคลิกอื่นได้)
    if action == "start_topic":
        start_generation_async(bot_token, chat_id, value)
        return

    # 2. กดเปลี่ยนหัวข้อถัดไป -> ข้ามหัวข้อนี้แล้วเสนอหัวข้อถัดไปให้ตรวจใหม่
    if action == "skip_topic":
        rows = read_topics_csv()
        for r in rows:
            if str(r.get("id")) == str(value) and r.get("status") in ("idea", "approved"):
                r["status"] = "skipped"
                break
        write_topics_csv(rows)
        next_row = get_or_replenish_next_idea_topic()
        send_topic_proposal(bot_token, chat_id, next_row)
        return

    # 3. กดอนุมัติ/ระงับวิดีโอที่สร้างเสร็จแล้ว
    clip_path = OUTPUT_DIR / value
    if not clip_path.exists():
        send_message(bot_token, chat_id, f"ไม่พบโฟลเดอร์คลิป: {value}")
        return

    if action == "approve":
        load_dotenv(ROOT_DIR / ".env", override=True)
        importlib.reload(mod_09)
        update_status(clip_path, "approved", note="อนุมัติผ่านปุ่มกด Telegram")
        send_message(bot_token, chat_id, f"กำลังอัปโหลด {value} ขึ้น YouTube Shorts...")
        res = mod_09.run_publish(clip_path)
        meta_file = clip_path / "meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        yt = meta.get("youtube", {})

        if res.get("youtube_url"):
            send_message(
                bot_token,
                chat_id,
                f"โพสต์ขึ้น YouTube Shorts สำเร็จ!\nลิงก์: {res['youtube_url']}",
            )
        else:
            send_message(
                bot_token,
                chat_id,
                f"อนุมัติและบันทึกสถานะ Published เรียบร้อย\n\n"
                f"ชื่อคลิป:\n{yt.get('title', '')}\n\n"
                f"คำอธิบาย:\n{yt.get('description', '')}\n\n"
                f"ไฟล์วิดีโอ: {clip_path / 'final.mp4'}",
            )
    elif action == "reject":
        update_status(clip_path, "rejected", note="ระงับผ่านปุ่มกด Telegram")
        send_message(
            bot_token,
            chat_id,
            f"ระงับคลิป {value} ไว้ก่อนแล้วครับ อยากให้ปรับแก้ตรงไหนพิมพ์บอกได้เลยครับ",
        )


def handle_text_message(bot_token: str, chat_id: str, text: str) -> None:
    clean_text = text.strip().strip('"\'')
    if clean_text.startswith("จำไว้ใช้กับทุกคลิป") and ":" in clean_text:
        new_rule = clean_text.split(":", 1)[1].strip()
        if new_rule:
            all_rules = add_custom_rule(new_rule)
            rule_list_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(all_rules))
            send_message(
                bot_token,
                chat_id,
                f"บันทึกกฎกลางสำหรับทุกคลิปเรียบร้อยแล้ว!\n\n"
                f"กฎที่เพิ่ม: \"{new_rule}\"\n\n"
                f"รายการกฎกลางทั้งหมดที่มีผลอยู่ตอนนี้ ({len(all_rules)} ข้อ):\n{rule_list_text}\n\n"
                f"ทุกคลิปที่สร้างใหม่ต่อจากนี้จะนำกฎนี้ไปใช้เขียนบทเสมอครับ",
            )
            return

    time_match = re.search(
        r"(?:เปลี่ยน|ตั้ง)เวลา(?:ส่ง|โพสต์|ผลิต)?(?:เป็น|\s+)?\s*(\d{1,2}[:.]\d{2})", text
    )
    if time_match:
        raw_t = time_match.group(1).replace(".", ":")
        parts = raw_t.split(":")
        new_time = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        channel_cfg = load_yaml("channel.yaml")
        channel_cfg.setdefault("workflow", {}).setdefault("daily_schedule", {})["time"] = new_time
        import yaml

        (ROOT_DIR / "config" / "channel.yaml").write_text(
            yaml.dump(channel_cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        send_message(
            bot_token,
            chat_id,
            f"ตั้งเวลาส่งคลิปประจำวันเป็น {new_time} น. เรียบร้อยแล้วครับ\nเมื่อถึงเวลาจะส่งมาให้ตรวจอนุมัติในแชตนี้อัตโนมัติ",
        )
        return

    decision = converse_and_route(text)
    reply_text = (decision.get("reply") or "").strip()
    action = decision.get("action", "none")

    if reply_text and action not in ("propose_custom_topic", "propose_next_topic"):
        send_message(bot_token, chat_id, reply_text)

    if action == "propose_custom_topic" and decision.get("topic_title"):
        title = decision["topic_title"].strip()
        slug = slugify(decision.get("slug") or title)
        hook = (decision.get("hook") or f"คุณเคยสงสัยไหม {title}?").strip()
        rows = read_topics_csv()
        next_id = max((int(r["id"]) for r in rows if str(r.get("id", "")).isdigit()), default=0) + 1
        new_row = {
            "id": str(next_id),
            "title": title,
            "slug": slug,
            "category": "ความรู้รอบตัว",
            "format": "why_question",
            "hook": hook,
            "status": "idea",
            "folder": "",
            "created_at": date.today().isoformat(),
        }
        rows.append(new_row)
        write_topics_csv(rows)
        send_topic_proposal(bot_token, chat_id, new_row)
        return

    if action == "propose_next_topic":
        next_row = get_or_replenish_next_idea_topic()
        send_topic_proposal(bot_token, chat_id, next_row)
        return

    if action == "change_voice":
        voice = decision.get("voice", "bualoi")
        if voice not in AVAILABLE_VOICES:
            voice = "bualoi"
        os.environ["TOKENME_VOICE"] = voice
        clip_path = get_latest_clip_dir()
        if not clip_path:
            send_message(bot_token, chat_id, "ยังไม่มีคลิปในระบบให้เปลี่ยนเสียงครับ")
            return
        mod_04.run_tts(clip_path)
        mod_06.run_subtitles(clip_path)
        mod_07.run_render(clip_path)
        mod_08.run_review(clip_path)
        return

    if action == "edit_script":
        clip_path = get_latest_clip_dir()
        if not clip_path:
            send_message(bot_token, chat_id, "ยังไม่มีคลิปในระบบให้แก้บทครับ")
            return
        instruction = decision.get("edit_instruction") or text
        script_file = clip_path / "script.json"
        cur_script = json.loads(script_file.read_text(encoding="utf-8"))
        custom_rules = get_custom_rules_prompt()
        edit_prompt = (
            f"แก้ไขบท JSON นี้ตามคำสั่งผู้ใช้: \"{instruction}\"\n"
            f"โดยคงจำนวนฉากเดิม ({len(cur_script.get('scenes', []))} ฉาก) เพื่อให้เข้ากับภาพที่มีอยู่แล้ว:\n"
            f"{json.dumps(cur_script, ensure_ascii=False, indent=2)}\n"
            f"{custom_rules}\n"
            "ตอบกลับเป็น JSON โครงสร้างเดิมเท่านั้น"
        )
        new_script = call_llm_json(edit_prompt)
        script_file.write_text(
            json.dumps(new_script, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        mod_04.run_tts(clip_path)
        mod_06.run_subtitles(clip_path)
        mod_07.run_render(clip_path)
        mod_08.run_review(clip_path)
        return

    if action == "generate_ideas":
        cat = decision.get("category") or "วิทยาศาสตร์ใกล้ตัว"
        added = mod_01.run_topics(category=cat)
        titles = "\n".join(f"- [{r['id']}] {r['title']}" for r in added[:5])
        send_message(
            bot_token,
            chat_id,
            f"เพิ่มลงคลังเรียบร้อย {len(added)} หัวข้อ:\n{titles}",
        )


def run_bot_loop() -> None:
    ensure_single_instance()
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    allowed_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not bot_token:
        raise RuntimeError("ไม่พบ TELEGRAM_BOT_TOKEN ใน .env")

    threading.Thread(
        target=daily_schedule_worker,
        args=(bot_token, allowed_chat),
        daemon=True,
    ).start()
    print("[telegram_bot] เริ่มระบบตั้งเวลาส่งงานประจำวัน (ทำงานเบื้องหลัง)...", flush=True)

    offset = 0
    print("[telegram_bot] เริ่มระบบ AI Producer (@sorap_yt_gen_bot)...", flush=True)

    try:
        with tg_client() as client:
            r = client.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")
            if r.status_code == 200:
                res = r.json().get("result", [])
                if res:
                    offset = int(res[-1]["update_id"]) + 1
                    pending_cb = sum(1 for u in res if "callback_query" in u)
                    if pending_cb:
                        print(
                            f"[telegram_bot] ข้าม callback ค้างจากรอบก่อน {pending_cb} รายการ (กดซ้ำได้)",
                            flush=True,
                        )
    except Exception as exc:
        print(f"[telegram_bot] ข้ามการดึง offset เริ่มต้น ({exc})", flush=True)

    while True:
        try:
            with tg_client() as client:
                resp = client.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params={"offset": offset, "timeout": 20},
                )
                resp.raise_for_status()
                updates = resp.json().get("result", [])

            for upd in updates:
                offset = max(offset, int(upd["update_id"]) + 1)

                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    cb_id = cb.get("id", "")
                    data = cb.get("data", "")
                    chat_id = str(cb.get("message", {}).get("chat", {}).get("id", allowed_chat))
                    print(f"[telegram_bot] รับ callback: {data}", flush=True)
                    if ":" in data:
                        try:
                            handle_callback(bot_token, chat_id, cb_id, data)
                        except Exception as cb_exc:
                            traceback.print_exc()
                            send_message(bot_token, chat_id, f"⚠️ การดำเนินการสะดุด: {cb_exc}")
                    continue

                msg = upd.get("message", {})
                text = (msg.get("text") or "").strip()
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if not text or (allowed_chat and chat_id != allowed_chat):
                    continue

                print(f"[telegram_bot] รับข้อความจาก {chat_id}: {text}", flush=True)
                try:
                    handle_text_message(bot_token, chat_id, text)
                except Exception as exc:
                    traceback.print_exc()
                    send_message(bot_token, chat_id, f"เกิดข้อผิดพลาดระหว่างทำงาน: {exc}")

        except KeyboardInterrupt:
            print("[telegram_bot] หยุดการทำงาน")
            break
        except Exception as exc:
            err_str = str(exc).lower()
            if any(k in err_str for k in ("timeout", "timed out", "handshake")):
                # Timeout บน long polling ของ Telegram เป็นภาวะปกติของ socket เมื่อไม่มีข้อความเข้า
                time.sleep(1)
            else:
                print(f"[telegram_bot] การเชื่อมต่อสะดุด ({exc}) รอ 3 วินาทีแล้วเชื่อมต่อใหม่...", flush=True)
                time.sleep(3)


if __name__ == "__main__":
    run_bot_loop()
