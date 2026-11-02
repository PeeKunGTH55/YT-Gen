from __future__ import annotations

import argparse
import csv
from datetime import date
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


def upload_youtube_direct(final_mp4: Path, meta: dict[str, Any]) -> str:
    token_env = os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")
    token_file = Path(token_env) if Path(token_env).is_absolute() else (ROOT_DIR / token_env)
    if not token_file.exists():
        raise FileNotFoundError(
            f"ไม่พบไฟล์ OAuth token สำหรับ YouTube ({token_file}) กรุณารัน python src/setup_youtube_auth.py ก่อน"
        )

    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_file(
        str(token_file), ["https://www.googleapis.com/auth/youtube.upload"]
    )
    youtube = build("youtube", "v3", credentials=creds)

    channel_cfg = load_yaml("channel.yaml")
    made_for_kids = bool(
        channel_cfg.get("workflow", {}).get("made_for_kids", False)
    )
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
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": made_for_kids,
            "selfDeclaredMadeWithAi": True,
        },
    }

    media = MediaFileUpload(str(final_mp4), mimetype="video/mp4", resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = req.execute()
    return f"https://youtube.com/shorts/{resp.get('id')}"


def append_performance_log(clip_path: Path, platforms: list[str]) -> None:
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
                    "notes": "initial_publish",
                }
            )


def run_publish(clip_dir: str | Path, mock: bool = False) -> dict[str, Any]:
    load_dotenv(ROOT_DIR / ".env", override=True)
    clip_path = resolve_clip_dir(clip_dir)
    meta = verify_publish_checklist(clip_path)
    final_mp4 = clip_path / "final.mp4"

    mode = "manual_export" if mock else os.getenv("PUBLISH_MODE", "manual_export").lower()
    result_info: dict[str, Any] = {"mode": mode, "platforms": []}

    if mode == "direct_api":
        yt_url = upload_youtube_direct(final_mp4, meta)
        result_info["youtube_url"] = yt_url
        result_info["platforms"].append("youtube")

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
        export_bundle = {
            "video_file": str(final_mp4.resolve()),
            "youtube_ready": meta.get("youtube", {}),
            "tiktok_ready": meta.get("tiktok", {}),
            "checklist_verified": True,
            "ai_label_required": True,
        }
        bundle_path = clip_path / "publish_bundle.json"
        bundle_path.write_text(
            json.dumps(export_bundle, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result_info["bundle_file"] = str(bundle_path)
        result_info["platforms"] = ["youtube_manual", "tiktok_manual"]

    append_performance_log(clip_path, result_info["platforms"])
    update_status(
        clip_path,
        "published",
        note=f"เผยแพร่สำเร็จผ่านโหมด {mode}",
        extra={"publish_result": result_info},
    )
    print(f"[09_publish] เผยแพร่คลิป {clip_path.name} สำเร็จ (mode={mode})")
    return result_info


def main() -> None:
    parser = argparse.ArgumentParser(description="09: ตรวจเช็กลิสต์และเผยแพร่คลิปขึ้น YouTube / TikTok")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="ใช้โหมดจำลองการโพสต์ (manual_export)")
    args = parser.parse_args()
    run_publish(args.clip, mock=args.mock)


if __name__ == "__main__":
    main()
