from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_secrets = ROOT_DIR / os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "client_secret.json")
    token_file = ROOT_DIR / os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")

    if not client_secrets.exists():
        raise FileNotFoundError(f"ไม่พบไฟล์ {client_secrets}")

    print("[setup_youtube_auth] กำลังเปิดเบราว์เซอร์เพื่อให้เลือกบัญชีและช่อง YouTube...", flush=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(
        port=8080,
        open_browser=True,
        prompt="consent",
        access_type="offline",
        authorization_prompt_message="\nหากเบราว์เซอร์ไม่เด้งอัตโนมัติ ให้เปิดลิงก์นี้:\n{url}\n",
        success_message="เชื่อมต่อช่อง YouTube สำเร็จแล้ว! คุณสามารถปิดหน้าต่างนี้ได้เลย",
    )
    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"\n[setup_youtube_auth] บันทึก Token สำเร็จที่: {token_file}", flush=True)


if __name__ == "__main__":
    main()
