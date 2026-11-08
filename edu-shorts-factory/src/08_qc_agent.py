from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.paths import get_ffmpeg_bin, load_yaml, resolve_clip_dir
from utils.status import read_status, update_status


def get_video_duration(final_mp4: Path) -> float:
    ffmpeg_bin = get_ffmpeg_bin()
    try:
        r = subprocess.run(
            [ffmpeg_bin, "-i", str(final_mp4)],
            capture_output=True,
            text=True,
            errors="replace",
        )
        for line in r.stderr.splitlines():
            if "Duration:" in line:
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                hours = float(parts[0])
                mins = float(parts[1])
                secs = float(parts[2])
                return hours * 3600 + mins * 60 + secs
    except Exception:
        pass
    return 0.0


def audit_clip_quality(clip_dir: str | Path, mock: bool = False) -> dict[str, Any]:
    clip_path = resolve_clip_dir(clip_dir)
    channel_cfg = load_yaml("channel.yaml")
    qc_cfg = channel_cfg.get("qc", {})

    min_pass_score = int(qc_cfg.get("min_pass_score", 85))
    strict_factcheck = bool(qc_cfg.get("strict_factcheck", True))
    blacklist = [
        phrase.lower().strip()
        for phrase in qc_cfg.get(
            "blacklist_hook_phrases",
            [
                "เคยสงสัยไหม",
                "คุณเคยสงสัยไหม",
                "เคยสงสัยไหมว่า",
                "รู้หรือไม่",
                "เคยได้ยินไหม",
                "คุณรู้ไหม",
                "สวัสดีครับ",
                "สวัสดีค่ะ",
            ],
        )
    ]

    violations: list[str] = []
    strengths: list[str] = []
    recommendations: list[str] = []

    # -------------------------------------------------------------
    # 1. Dimension: Hook Quality & VVSA Potential (Weight: 30)
    # -------------------------------------------------------------
    hook_score = 30
    script_file = clip_path / "script.json"
    hooks_file = clip_path / "hooks.json"
    hook_text = ""
    scene1_text = ""

    if script_file.exists():
        sdata = json.loads(script_file.read_text(encoding="utf-8"))
        scenes = sdata.get("scenes", [])
        if scenes:
            scene1_text = scenes[0].get("narration", "").strip()

    if hooks_file.exists():
        hdata = json.loads(hooks_file.read_text(encoding="utf-8"))
        hook_text = hdata.get("recommended_hook", "").strip()

    eval_text = (scene1_text or hook_text).lower()

    # Check blacklist
    found_banned = [p for p in blacklist if p in eval_text]
    if found_banned:
        hook_score = 0
        violations.append(
            f"Hook ใช้คำต้องห้าม: '{', '.join(found_banned)}' (เสี่ยงคนดูปัดทิ้งสูงมาก)"
        )
        recommendations.append("เปลี่ยนประโยคเปิดเป็น Contrast หรือ Shocking Fact ทันที")
    else:
        # Check punchiness & word length
        thai_word_est = len(eval_text.split())
        if len(eval_text) > 90 or thai_word_est > 25:
            hook_score -= 8
            recommendations.append("Hook ยาวเกินไป ควรกระชับไม่เกิน 12-14 คำ")
        else:
            strengths.append("Hook สั้นกระชับ ไม่มีคำต้องห้าม")

    # -------------------------------------------------------------
    # 2. Dimension: Fact & Citation Confidence (Weight: 35)
    # -------------------------------------------------------------
    fact_score = 35
    factcheck_file = clip_path / "factcheck.json"
    if not factcheck_file.exists():
        fact_score = 0
        violations.append("ไม่พบไฟล์ factcheck.json (ยังไม่ได้ตรวจข้อเท็จจริง)")
    else:
        fc = json.loads(factcheck_file.read_text(encoding="utf-8"))
        if fc.get("overall") != "pass":
            fact_score = 0
            violations.append(f"ผลตรวจข้อเท็จจริงไม่ผ่าน (overall={fc.get('overall')})")

        results = fc.get("results", [])
        missing_sources = 0
        wrong_claims = 0
        for r in results:
            if r.get("verdict") != "correct":
                wrong_claims += 1
            source_url = (r.get("source_url") or "").strip()
            if not source_url.startswith("http"):
                missing_sources += 1

        if wrong_claims > 0:
            fact_score -= (wrong_claims * 15)
            violations.append(f"มี {wrong_claims} ประเด็นที่ข้อเท็จจริงไม่ถูกต้องหรือคลุมเครือ")

        if missing_sources > 0:
            if strict_factcheck:
                fact_score -= (missing_sources * 10)
                violations.append(f"มี {missing_sources} ประเด็นที่ขาดแหล่งอ้างอิง URL ชัดเจน")
            else:
                fact_score -= (missing_sources * 5)
                recommendations.append("ควรเพิ่มแหล่งอ้างอิง URL ให้ครบทุกประเด็น")

        fact_score = max(0, fact_score)
        if fact_score >= 30 and not violations:
            strengths.append("ข้อมูลวิทยาศาสตร์ถูกต้อง 100% พร้อมแหล่งอ้างอิงชัดเจน")

    # -------------------------------------------------------------
    # 3. Dimension: Duration & Pacing (Weight: 20)
    # -------------------------------------------------------------
    pacing_score = 20
    final_mp4 = clip_path / "final.mp4"
    dur = 0.0
    if final_mp4.exists():
        dur = get_video_duration(final_mp4)
    elif (clip_path / "audio" / "manifest.json").exists():
        man = json.loads((clip_path / "audio" / "manifest.json").read_text(encoding="utf-8"))
        dur = float(man.get("total_duration_sec", 0))

    if dur > 0:
        if 18.0 <= dur <= 27.0:
            strengths.append(f"ความยาวคลิปสมบูรณ์แบบ ({dur:.1f}s) อยู่ใน Sweet Spot สำหรับ Shorts")
        elif 27.0 < dur <= 31.0:
            pacing_score = 15
            recommendations.append(f"ความยาวคลิป {dur:.1f}s (สามารถบีบให้สั้นลงเหลือ 22-25s เพื่อดัน Retention เพิ่มได้)")
        elif 31.0 < dur <= 36.0:
            pacing_score = 10
            violations.append(f"คลิปยาวเกินเกณฑ์กระชับ ({dur:.1f}s > 31s)")
        else:
            pacing_score = 5
            violations.append(f"คลิปยาวเกินไปมาก ({dur:.1f}s) เสี่ยงคนดูหลุดกลางคัน")

    # Check scene count
    if script_file.exists():
        sdata = json.loads(script_file.read_text(encoding="utf-8"))
        scene_count = len(sdata.get("scenes", []))
        if scene_count > 6:
            pacing_score = max(0, pacing_score - 5)
            recommendations.append(f"จำนวนฉาก ({scene_count} ฉาก) มากเกินไป แนะนำ 5-6 ฉาก")

    # -------------------------------------------------------------
    # 4. Dimension: Asset & Integrity (Weight: 15)
    # -------------------------------------------------------------
    integrity_score = 15
    if not final_mp4.exists() or final_mp4.stat().st_size < 100_000:
        integrity_score -= 10
        violations.append("ไฟล์ final.mp4 ไม่สมบูรณ์หรือขนาดเล็กผิดปกติ")

    subs_file = clip_path / "subs.ass"
    if not subs_file.exists() or subs_file.stat().st_size < 100:
        integrity_score -= 5
        violations.append("ไฟล์ซับไตเติล subs.ass ไม่สมบูรณ์")

    meta_file = clip_path / "meta.json"
    if not meta_file.exists():
        integrity_score -= 5
        violations.append("ไม่พบไฟล์ meta.json")
    else:
        mdata = json.loads(meta_file.read_text(encoding="utf-8"))
        yt_title = mdata.get("youtube", {}).get("title", "")
        if not yt_title:
            integrity_score -= 3
            violations.append("meta.json ไม่มีชื่อคลิป YouTube")

    integrity_score = max(0, integrity_score)
    if integrity_score == 15:
        strengths.append("ไฟล์วิดีโอ ซับไตเติล และ Metadata สมบูรณ์ 100%")

    # -------------------------------------------------------------
    # Final Decision Calculation
    # -------------------------------------------------------------
    total_score = hook_score + fact_score + pacing_score + integrity_score
    has_hard_violations = len(violations) > 0
    passed = (total_score >= min_pass_score) and not has_hard_violations

    decision = "approved" if passed else "rejected_by_qc"

    report = {
        "timestamp": datetime.now().isoformat(),
        "clip_folder": clip_path.name,
        "total_score": total_score,
        "min_pass_score": min_pass_score,
        "passed": passed,
        "decision": decision,
        "breakdown": {
            "hook_quality": {"score": hook_score, "max": 30},
            "fact_confidence": {"score": fact_score, "max": 35},
            "duration_pacing": {"score": pacing_score, "max": 20, "duration_sec": round(dur, 2)},
            "asset_integrity": {"score": integrity_score, "max": 15},
        },
        "violations": violations,
        "strengths": strengths,
        "recommendations": recommendations,
    }

    # Save QC Report
    (clip_path / "qc_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return report


def run_qc_review(clip_dir: str | Path, mock: bool = False) -> tuple[str, dict[str, Any]]:
    clip_path = resolve_clip_dir(clip_dir)
    report = audit_clip_quality(clip_path, mock=mock)

    if report["passed"]:
        update_status(
            clip_path,
            "approved",
            note=f"ผ่านการตรวจสอบคุณภาพโดย QC Subagent (คะแนน: {report['total_score']}/{report['min_pass_score']})",
            extra={"qc_report": report},
        )
        print(f"[08_qc_agent]  คลิป {clip_path.name} ผ่านเกณฑ์ QC (คะแนน {report['total_score']}/100) -> อนุมัติอัตโนมัติ")
        return "approved", report
    else:
        update_status(
            clip_path,
            "awaiting_approval",
            note=f"ไม่ผ่านเกณฑ์ QC Subagent (คะแนน: {report['total_score']}/{report['min_pass_score']}) ส่งให้คนตรวจ",
            extra={"qc_report": report},
        )
        print(f"[08_qc_agent] ⚠️ คลิป {clip_path.name} ไม่ผ่านเกณฑ์ QC (คะแนน {report['total_score']}/100)")
        for v in report["violations"]:
            print(f"   - {v}")
        return "awaiting_approval", report


def main() -> None:
    parser = argparse.ArgumentParser(description="08: QC Critic Subagent ตรวจสอบคุณภาพคลิปก่อนอนุมัติ")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="โหมดจำลอง")
    args = parser.parse_args()

    decision, report = run_qc_review(args.clip, mock=args.mock)
    print(f"Result: {decision}")


if __name__ == "__main__":
    main()
