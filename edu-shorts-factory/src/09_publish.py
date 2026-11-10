from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import json
import os
import sys
from pathlib import Path
from typing import Any
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from utils.paths import DATA_DIR, ROOT_DIR, load_yaml, resolve_clip_dir
from utils.status import read_status, update_status


def get_next_schedule_slot(channel_cfg: dict[str, Any]) -> tuple[str, str]:
    """คำนวณช่วงเวลาปล่อยคลิปถัดไปตามสล็อตที่กำหนดใน channel.yaml (Option 3: Schedule)

    คืนค่าเป็น (publish_at_utc_iso, local_time_display_str)
    """
    sched_cfg = channel_cfg.get("schedule", {})
    slots = sched_cfg.get("time_slots", ["11:30", "17:30", "20:30"])
    tz_offset = int(sched_cfg.get("timezone_offset_hours", 7))
    min_lead = int(sched_cfg.get("min_lead_minutes", 20))

    tz_local = timezone(timedelta(hours=tz_offset))
    now_local = datetime.now(tz_local)

    # ตรวจสอบสล็อตที่มีการจองไว้แล้วใน performance.csv หรือคลิปก่อนหน้า
    booked_slots: set[str] = set()
    perf_file = DATA_DIR / "performance.csv"
    if perf_file.exists():
        try:
            with perf_file.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    notes = r.get("notes", "")
                    if "scheduled_at:" in notes:
                        val = notes.split("scheduled_at:")[1].strip()
                        booked_slots.add(val[:16])
        except Exception:
            pass

    # ค้นหาสล็อตว่างถัดไปภายใน 7 วันข้างหน้า
    for day_offset in range(7):
        target_date = now_local.date() + timedelta(days=day_offset)
        for slot_str in slots:
            parts = slot_str.split(":")
            hh = int(parts[0])
            mm = int(parts[1]) if len(parts) > 1 else 0
            slot_dt = datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                hh,
                mm,
                0,
                tzinfo=tz_local,
            )

            # ต้องห่างจากปัจจุบันอย่างน้อย min_lead นาที
            if slot_dt <= (now_local + timedelta(minutes=min_lead)):
                continue

            slot_key = slot_dt.strftime("%Y-%m-%d %H:%M")
            if slot_key in booked_slots:
                continue

            # เจอสล็อตว่างที่ยังไม่มีการตั้งเวลา
            slot_utc = slot_dt.astimezone(timezone.utc)
            utc_iso = slot_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            local_display = slot_dt.strftime("%Y-%m-%d %H:%M:%S (GMT+7)")
            return utc_iso, local_display

    # กรณีฉุกเฉิน: 3 ชั่วโมงนับจากปัจจุบัน
    fallback_dt = now_local + timedelta(hours=3)
    fallback_utc = fallback_dt.astimezone(timezone.utc)
    return (
        fallback_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        fallback_dt.strftime("%Y-%m-%d %H:%M:%S (GMT+7)"),
    )


def verify_publish_checklist(clip_path: Path) -> dict[str, Any]:
    channel_cfg = load_yaml("channel.yaml")
    require_approval = bool(channel_cfg.get("workflow", {}).get("require_approval", True))
    max_dur = float(
        channel_cfg.get("video", {}).get("duration_sec", {}).get("hard_max", 60)
    )

    st = read_status(clip_path)
    if require_approval and st.get("status") not in ("approved", "published"):
        raise RuntimeError(
            f"ไม่อนุญาตให้โพสต์: สถานะปัจจุบันคือ '{st.get('status')}' (ต้องเป็น 'approved')"
        )

    final_mp4 = clip_path / "final.mp4"
    if not final_mp4.exists():
        raise FileNotFoundError(f"ไม่พบไฟล์วิดีโอ {final_mp4}")

    factcheck_file = clip_path / "factcheck.json"
    if not factcheck_file.exists():
        raise FileNotFoundError("ไม่พบไฟล์ factcheck.json ห้ามโพสต์คลิปที่ไม่ผ่านการตรวจข้อเท็จจริง")
    fc = json.loads(factcheck_file.read_text(encoding="utf-8"))
    if fc.get("overall") != "pass":
        raise RuntimeError(f"ผลตรวจข้อเท็จจริงไม่ใช่ pass ({fc.get('overall')})")

    manifest_file = clip_path / "audio" / "manifest.json"
    if manifest_file.exists():
        dur = float(
            json.loads(manifest_file.read_text(encoding="utf-8")).get("total_duration_sec", 0)
        )
        if dur > max_dur:
            raise RuntimeError(f"ความยาวคลิป ({dur}s) เกินเพดานสูงสุด {max_dur}s")

    meta_file = clip_path / "meta.json"
    if not meta_file.exists():
        raise FileNotFoundError("ไม่พบไฟล์ meta.json")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return meta


def upload_youtube_direct(final_mp4: Path, meta: dict[str, Any]) -> tuple[str, str | None]:
    token_env = os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
    token_file = Path(token_env) if Path(token_env).is_absolute() else (ROOT_DIR / token_env)
    if not token_file.exists():
        raise FileNotFoundError(
            f"ไม่พบไฟล์ OAuth token สำหรับ YouTube ({token_file}) กรุณารัน python src/setup_youtube_auth.py ก่อน"
        )

    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google.auth.exceptions import RefreshError
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_file(
        str(token_file), ["https://www.googleapis.com/auth/youtube.upload"]
    )
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_file.write_text(creds.to_json(), encoding="utf-8")
        except RefreshError as exc:
            raise RuntimeError(
                f"YouTube OAuth Token หมดอายุหรือถูกเพิกถอน ({exc})\n"
                f"กรุณารันคำสั่ง 'python src/setup_youtube_auth.py' เพื่อล็อกอินใหม่\n"
                f"(คำแนะนำ: หากแอปยังอยู่ในสถานะ Testing ใน Google Cloud Console โทเค็นจะหมดอายุทุก 7 วัน แนะนำให้กดปุ่ม 'Publish App' ให้เป็น 'In production')"
            ) from exc

    youtube = build("youtube", "v3", credentials=creds)

    channel_cfg = load_yaml("channel.yaml")
    made_for_kids = bool(
        channel_cfg.get("workflow", {}).get("made_for_kids", False)
    )
    schedule_cfg = channel_cfg.get("schedule", {})
    schedule_enabled = bool(schedule_cfg.get("enabled", True))

    scheduled_utc_iso: str | None = None
    scheduled_local_str: str | None = None

    if schedule_enabled:
        scheduled_utc_iso, scheduled_local_str = get_next_schedule_slot(channel_cfg)

    yt_meta = meta.get("youtube", {})
    body = {
        "snippet": {
            "title": yt_meta.get("title", "ความรู้สั้น 30 วินาที #Shorts")[:100],
            "description": yt_meta.get("description", ""),
            "tags": yt_meta.get("tags", []),
            "categoryId": "27",  # Education
            "defaultLanguage": "th",
            "defaultAudioLanguage": "th",
        },
        "status": {
            "selfDeclaredMadeForKids": made_for_kids,
            "selfDeclaredMadeWithAi": True,
        },
    }

    if scheduled_utc_iso:
        # YouTube กำหนดว่า หากใส่ publishAt ต้องตั้ง privacyStatus เป็น private
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = scheduled_utc_iso
        print(f"[09_publish] ⏰ ตั้งเวลาเผยแพร่ YouTube Shorts: {scheduled_local_str} (UTC: {scheduled_utc_iso})")
    else:
        body["status"]["privacyStatus"] = "public"

    media = MediaFileUpload(str(final_mp4), mimetype="video/mp4", resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    try:
        resp = req.execute()
    except RefreshError as exc:
        raise RuntimeError(
            f"YouTube OAuth Token หมดอายุหรือถูกเพิกถอน ({exc})\n"
            f"กรุณารันคำสั่ง 'python src/setup_youtube_auth.py' เพื่อล็อกอินใหม่\n"
            f"(คำแนะนำ: หากแอปยังอยู่ในสถานะ Testing ใน Google Cloud Console โทเค็นจะหมดอายุทุก 7 วัน แนะนำให้กดปุ่ม 'Publish App' ให้เป็น 'In production')"
        ) from exc

    # บันทึก Token ล่าสุดเก็บไว้หากมีการ refresh สำเร็จ
    try:
        if creds and creds.valid:
            token_file.write_text(creds.to_json(), encoding="utf-8")
    except Exception:
        pass

    video_id = resp.get("id")

    return f"https://youtube.com/shorts/{video_id}", scheduled_local_str


def append_performance_log(
    clip_path: Path, platforms: list[str], scheduled_at: str | None = None
) -> None:
    perf_csv = DATA_DIR / "performance.csv"
    st = read_status(clip_path)
    hooks_file = clip_path / "hooks.json"
    hook_pattern = "why_question"
    if hooks_file.exists():
        hdata = json.loads(hooks_file.read_text(encoding="utf-8"))
        rec = hdata.get("recommended_hook", "")
        for v in hdata.get("variants", []):
            if v.get("hook") == rec:
                hook_pattern = v.get("pattern", "why_question")
                break

    file_exists = perf_csv.exists() and perf_csv.stat().st_size > 0
    fieldnames = [
        "clip_folder",
        "topic_id",
        "format",
        "hook_pattern",
        "published_date",
        "platform",
        "views",
        "avg_view_duration_sec",
        "completion_rate_percent",
        "likes",
        "notes",
    ]
    with perf_csv.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        notes_text = f"scheduled_at: {scheduled_at}" if scheduled_at else "initial_publish"
        for pf in platforms:
            writer.writerow(
                {
                    "clip_folder": clip_path.name,
                    "topic_id": st.get("topic_id", ""),
                    "format": st.get("format", ""),
                    "hook_pattern": hook_pattern,
                    "published_date": date.today().isoformat(),
                    "platform": pf,
                    "views": "0",
                    "avg_view_duration_sec": "0",
                    "completion_rate_percent": "0",
                    "likes": "0",
                    "notes": notes_text,
                }
            )


def run_publish(clip_dir: str | Path, mock: bool = False) -> dict[str, Any]:
    load_dotenv(ROOT_DIR / ".env", override=True)
    clip_path = resolve_clip_dir(clip_dir)
    meta = verify_publish_checklist(clip_path)
    final_mp4 = clip_path / "final.mp4"

    mode = "manual_export" if mock else os.getenv("PUBLISH_MODE", "manual_export").lower()
    result_info: dict[str, Any] = {"mode": mode, "platforms": []}

    scheduled_at: str | None = None

    if mode == "direct_api":
        yt_url, scheduled_at = upload_youtube_direct(final_mp4, meta)
        result_info["youtube_url"] = yt_url
        result_info["platforms"].append("youtube")
        if scheduled_at:
            result_info["scheduled_at"] = scheduled_at

        tiktok_token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
        if tiktok_token:
            result_info["platforms"].append("tiktok")
    elif mode == "ayrshare":
        ayr_key = os.getenv("AYRSHARE_API_KEY", "")
        if not ayr_key:
            raise RuntimeError("ไม่พบ AYRSHARE_API_KEY ใน .env")
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                "https://app.ayrshare.com/api/post",
                headers={"Authorization": f"Bearer {ayr_key}"},
                json={
                    "post": meta.get("tiktok", {}).get("caption", ""),
                    "platforms": ["youtube", "tiktok"],
                    "youTubeOptions": {
                        "title": meta.get("youtube", {}).get("title", ""),
                        "visibility": "public",
                        "shorts": True,
                        "madeWithAi": True,
                    },
                },
            )
            resp.raise_for_status()
            result_info["ayrshare_response"] = resp.json()
            result_info["platforms"] = ["youtube", "tiktok"]
    else:
        channel_cfg = load_yaml("channel.yaml")
        _, scheduled_at = get_next_schedule_slot(channel_cfg)
        export_bundle = {
            "video_file": str(final_mp4.resolve()),
            "youtube_ready": meta.get("youtube", {}),
            "tiktok_ready": meta.get("tiktok", {}),
            "scheduled_at": scheduled_at,
            "checklist_verified": True,
            "ai_label_required": True,
        }
        bundle_path = clip_path / "publish_bundle.json"
        bundle_path.write_text(
            json.dumps(export_bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result_info["bundle_file"] = str(bundle_path)
        result_info["scheduled_at"] = scheduled_at
        result_info["platforms"] = ["youtube_manual", "tiktok_manual"]

    append_performance_log(clip_path, result_info["platforms"], scheduled_at=scheduled_at)
    status_note = f"เผยแพร่สำเร็จผ่านโหมด {mode}"
    if scheduled_at:
        status_note += f" (ตั้งเวลาปล่อย: {scheduled_at})"

    update_status(
        clip_path,
        "published",
        note=status_note,
        extra={"publish_result": result_info},
    )
    print(f"[09_publish] เผยแพร่คลิป {clip_path.name} สำเร็จ (mode={mode})")
    if scheduled_at:
        print(f"            กำหนดปล่อยวิดีโอ: {scheduled_at}")
    return result_info


def main() -> None:
    parser = argparse.ArgumentParser(description="09: ตรวจเช็กลิสต์และเผยแพร่/ตั้งเวลาคลิปขึ้น YouTube / TikTok")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="โหมดจำลองไม่ยิง API จริง")
    args = parser.parse_args()

    run_publish(args.clip, mock=args.mock)


if __name__ == "__main__":
    main()
