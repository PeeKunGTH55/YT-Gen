from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm import call_llm_json, search_and_fetch_claims_batch
from utils.paths import load_yaml, render_prompt, resolve_clip_dir
from utils.status import update_status


def build_mock_factcheck(script_data: dict[str, Any]) -> dict[str, Any]:
    results = []
    for scene in script_data.get("scenes", []):
        for claim in scene.get("claims", []):
            results.append(
                {
                    "scene_id": scene.get("id", 1),
                    "claim": claim,
                    "verdict": "correct",
                    "source_title": "NASA Space Place — Why Is the Sky Blue?",
                    "source_url": "https://spaceplace.nasa.gov/blue-sky/en/",
                    "fix": "",
                }
            )
    return {
        "results": results,
        "analogy_check": "ok",
        "overall": "pass",
    }


def apply_fixes_to_script(
    script_data: dict[str, Any], factcheck_data: dict[str, Any]
) -> bool:
    changed = False
    scenes_by_id = {int(s["id"]): s for s in script_data.get("scenes", []) if "id" in s}

    for item in factcheck_data.get("results", []):
        verdict = item.get("verdict", "correct")
        fix_text = (item.get("fix") or "").strip()
        if verdict in ("unclear", "wrong") and fix_text:
            sid = item.get("scene_id")
            if sid and int(sid) in scenes_by_id:
                scenes_by_id[int(sid)]["narration"] = fix_text
                scenes_by_id[int(sid)]["claims"] = [fix_text]
                changed = True
            else:
                claim_str = item.get("claim", "")
                for s in script_data.get("scenes", []):
                    if claim_str in s.get("claims", []):
                        s["narration"] = fix_text
                        s["claims"] = [fix_text]
                        changed = True
                        break
    return changed


def run_factcheck(clip_dir: str | Path, mock: bool = False) -> dict[str, Any]:
    clip_path = resolve_clip_dir(clip_dir)
    script_file = clip_path / "script.json"
    if not script_file.exists():
        raise FileNotFoundError(f"ไม่พบไฟล์ {script_file} กรุณารัน 02_script.py ก่อน")

    channel_cfg = load_yaml("channel.yaml")
    max_retries = int(channel_cfg.get("workflow", {}).get("factcheck_max_retries", 2))

    script_data = json.loads(script_file.read_text(encoding="utf-8"))
    factcheck_data: dict[str, Any] = {}

    for attempt in range(max_retries + 1):
        all_claims: list[str] = []
        for s in script_data.get("scenes", []):
            all_claims.extend(s.get("claims", []))

        search_bundles = search_and_fetch_claims_batch(all_claims, force_mock=mock)

        prompt = render_prompt(
            "03_factcheck.md",
            script_json=json.dumps(script_data, ensure_ascii=False, indent=2),
            search_context=json.dumps(search_bundles, ensure_ascii=False, indent=2),
        )

        factcheck_data = call_llm_json(
            prompt,
            mock_response=build_mock_factcheck(script_data),
            force_mock=mock,
        )
        factcheck_data["attempt"] = attempt + 1

        overall = factcheck_data.get("overall", "reject")
        analogy = factcheck_data.get("analogy_check", "ok")

        if overall == "pass" and analogy == "ok":
            (clip_path / "factcheck.json").write_text(
                json.dumps(factcheck_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            update_status(
                clip_path,
                "factchecked",
                note=f"ผ่านการตรวจข้อเท็จจริงในรอบที่ {attempt + 1}",
            )
            print(f"[03_factcheck] ผ่านการตรวจข้อเท็จจริง (รอบที่ {attempt + 1})")
            return factcheck_data

        if overall == "reject":
            break

        if attempt < max_retries:
            was_updated = apply_fixes_to_script(script_data, factcheck_data)
            if was_updated:
                script_file.write_text(
                    json.dumps(script_data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(
                    f"[03_factcheck] แก้ไข script.json อัตโนมัติตามคำแนะนำ (รอบที่ {attempt + 1}) และกำลังตรวจซ้ำ..."
                )
                continue
            break

    (clip_path / "factcheck.json").write_text(
        json.dumps(factcheck_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    update_status(
        clip_path,
        "failed_factcheck",
        note=f"ไม่ผ่านการตรวจข้อเท็จจริง (overall={factcheck_data.get('overall')})",
    )
    raise RuntimeError(
        f"[03_factcheck] ไม่ผ่านการตรวจข้อเท็จจริงสำหรับ {clip_path.name} กรุณาตรวจสอบ factcheck.json"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="03: ตรวจสอบข้อเท็จจริงพร้อม Auto-fix สูงสุด 2 รอบ")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="ใช้โหมดจำลองข้อมูล")
    args = parser.parse_args()
    run_factcheck(args.clip, mock=args.mock)


if __name__ == "__main__":
    main()
