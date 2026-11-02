from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import DATA_DIR

VALID_STATES = [
    "idea",
    "scripted",
    "factchecked",
    "assets_ready",
    "rendered",
    "awaiting_approval",
    "approved",
    "published",
    "failed_factcheck",
    "rejected",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_status(clip_dir: Path) -> dict[str, Any]:
    status_file = clip_dir / "status.json"
    if not status_file.exists():
        return {
            "folder": clip_dir.name,
            "status": "idea",
            "history": [],
            "updated_at": now_iso(),
        }
    return json.loads(status_file.read_text(encoding="utf-8"))


def update_status(
    clip_dir: Path,
    new_status: str,
    note: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if new_status not in VALID_STATES:
        raise ValueError(f"สถานะไม่ถูกต้อง: {new_status}")

    data = read_status(clip_dir)
    data["status"] = new_status
    data["updated_at"] = now_iso()
    if extra:
        data.update(extra)

    history = data.setdefault("history", [])
    history.append(
        {
            "status": new_status,
            "timestamp": data["updated_at"],
            "note": note,
        }
    )

    status_file = clip_dir / "status.json"
    status_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    topic_id = data.get("topic_id")
    if topic_id is not None:
        sync_topic_csv_status(str(topic_id), new_status, clip_dir.name)

    return data


def read_topics_csv() -> list[dict[str, str]]:
    csv_path = DATA_DIR / "topics.csv"
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_topics_csv(rows: list[dict[str, str]]) -> None:
    csv_path = DATA_DIR / "topics.csv"
    fieldnames = [
        "id",
        "title",
        "slug",
        "category",
        "format",
        "hook",
        "status",
        "folder",
        "created_at",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def sync_topic_csv_status(topic_id: str, status: str, folder_name: str = "") -> None:
    rows = read_topics_csv()
    changed = False
    for row in rows:
        if str(row.get("id")) == str(topic_id):
            row["status"] = status
            if folder_name:
                row["folder"] = folder_name
            changed = True
            break
    if changed:
        write_topics_csv(rows)
