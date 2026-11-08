import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[1]
STARTUP_DIR = (
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
)
SHORTCUT_PATH = STARTUP_DIR / "NongSongSaiBot.lnk"
BAT_PATH = ROOT_DIR / "start_telegram_bot.bat"


def main() -> None:
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "install"

    if action in ("uninstall", "remove", "delete"):
        if SHORTCUT_PATH.exists():
            SHORTCUT_PATH.unlink()
            print("[สำเร็จ] ยกเลิกการเปิดบอทอัตโนมัติเมื่อเปิดเครื่องเรียบร้อยแล้ว")
        else:
            print("[แจ้งเตือน] ไม่พบไฟล์ Shortcut ในโฟลเดอร์ Startup อยู่แล้ว")
        return

    import subprocess

    ps_cmd = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{SHORTCUT_PATH}'); "
        f"$s.TargetPath = '{BAT_PATH}'; "
        f"$s.WorkingDirectory = '{ROOT_DIR}'; "
        f"$s.WindowStyle = 7; "
        f"$s.Description = 'NongSongSai Telegram Bot'; "
        f"$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)

    if SHORTCUT_PATH.exists():
        print("[สำเร็จ] ตั้งค่าให้บอทเปิดทำงานอัตโนมัติเมื่อเปิดเครื่องเรียบร้อยแล้ว!")
        print(f"ตำแหน่ง Shortcut: {SHORTCUT_PATH}")
        print(
            "(เมื่อเปิดเครื่อง บอทจะเปิดแบบย่อหน้าต่าง Minimized ไว้ที่ Taskbar ทำงานเบื้องหลัง ไม่กวนสายตา)"
        )
    else:
        print("[เกิดข้อผิดพลาด] ไม่สามารถสร้าง Shortcut ในโฟลเดอร์ Startup ได้")


if __name__ == "__main__":
    main()
