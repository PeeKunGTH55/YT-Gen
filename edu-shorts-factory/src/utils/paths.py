from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Any
import yaml
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
PROMPTS_DIR = ROOT_DIR / "prompts"
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
ASSETS_DIR = ROOT_DIR / "assets"
LOGS_DIR = ROOT_DIR / "logs"

load_dotenv(ROOT_DIR / ".env")


def ensure_base_dirs() -> None:
    for d in (CONFIG_DIR, PROMPTS_DIR, DATA_DIR, OUTPUT_DIR, ASSETS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "bgm").mkdir(parents=True, exist_ok=True)
    (ASSETS_DIR / "fonts").mkdir(parents=True, exist_ok=True)


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs: Any) -> str:
    text = load_prompt(name)
    for k, v in kwargs.items():
        text = text.replace(f"{{{k}}}", str(v))
    return text


def parse_style_guide() -> dict[str, str]:
    text = (CONFIG_DIR / "style_guide.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```text\s*(.*?)\s*```", text, flags=re.DOTALL)
    style_prefix = (
        blocks[0].strip()
        if len(blocks) >= 1
        else "flat vector illustration, soft pastel colors, rounded shapes, friendly simple characters, clean light background, no text, suitable for all ages"
    )
    character_description = (
        blocks[1].strip()
        if len(blocks) >= 2
        else "a friendly round-faced curious kid character wearing a bright yellow hoodie and round glasses"
    )
    return {
        "style_prefix": style_prefix,
        "character_description": character_description,
    }


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9\-_]+", "-", value.strip().lower()).strip("-")
    return cleaned or "topic-clip"


def get_or_create_clip_dir(slug: str, target_date: str | None = None) -> Path:
    ensure_base_dirs()
    prefix = target_date or date.today().isoformat()
    folder_name = f"{prefix}_{slugify(slug)}"
    clip_dir = OUTPUT_DIR / folder_name
    clip_dir.mkdir(parents=True, exist_ok=True)
    (clip_dir / "audio").mkdir(parents=True, exist_ok=True)
    (clip_dir / "images").mkdir(parents=True, exist_ok=True)
    return clip_dir


def resolve_clip_dir(clip_arg: str | Path) -> Path:
    p = Path(clip_arg)
    if p.is_dir():
        return p.resolve()
    candidate = OUTPUT_DIR / str(clip_arg)
    if candidate.is_dir():
        return candidate.resolve()
    raise FileNotFoundError(f"ไม่พบโฟลเดอร์คลิป: {clip_arg}")


def get_ffmpeg_bin() -> str:
    env_bin = os.getenv("FFMPEG_BINARY")
    if env_bin and Path(env_bin).exists():
        return env_bin
    which_bin = shutil.which("ffmpeg")
    if which_bin:
        return which_bin
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


CUSTOM_RULES_FILE = CONFIG_DIR / "custom_rules.txt"


def load_custom_rules() -> list[str]:
    if not CUSTOM_RULES_FILE.exists():
        return []
    lines = [
        line.strip().lstrip("-* ").strip()
        for line in CUSTOM_RULES_FILE.read_text(encoding="utf-8").splitlines()
    ]
    return [l for l in lines if l]


def add_custom_rule(rule: str) -> list[str]:
    rules = load_custom_rules()
    cleaned = rule.strip().lstrip("-* ").strip()
    if cleaned and cleaned not in rules:
        rules.append(cleaned)
        CUSTOM_RULES_FILE.write_text(
            "\n".join(f"- {r}" for r in rules) + "\n", encoding="utf-8"
        )
    return rules


def get_custom_rules_prompt() -> str:
    rules = load_custom_rules()
    if not rules:
        return ""
    bullet_list = "\n".join(f"- {r}" for r in rules)
    return f"\n\nกฎสำคัญเพิ่มเติมที่เจ้าของช่องกำหนด (ต้องปฏิบัติตามอย่างเคร่งครัดในทุกฉาก):\n{bullet_list}\n"


