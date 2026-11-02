from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm import call_llm_json, get_genai_client
from utils.paths import ASSETS_DIR, get_ffmpeg_bin, load_yaml, render_prompt, resolve_clip_dir
from utils.status import update_status


def build_mock_metadata(
    script_data: dict[str, Any], factcheck_data: dict[str, Any]
) -> dict[str, Any]:
    title = script_data.get("title", "ทำไมท้องฟ้าถึงเป็นสีฟ้า")
    urls = []
    for r in factcheck_data.get("results", []):
        u = r.get("source_url", "")
        if u and u not in urls:
            urls.append(u)
    ref_line = urls[0] if urls else "https://spaceplace.nasa.gov/blue-sky/en/"
    return {
        "youtube": {
            "title": f"{title[:48]} #Shorts",
            "description": (
                f"สรุปคำตอบเข้าใจง่ายใน 30 วินาที: {title}\n"
                f"แหล่งอ้างอิง: {ref_line}\n"
                "คลิปนี้สร้างด้วยความช่วยเหลือของ AI"
            ),
            "tags": ["ความรู้รอบตัว", "วิทยาศาสตร์", "สาระน่ารู้", "Shorts", "การศึกษา"],
        },
        "tiktok": {
            "caption": f"{title} #ความรู้รอบตัว #วิทยาศาสตร์ใกล้ตัว #สาระน่ารู้ #TikTokUni",
            "ai_label": True,
        },
        "thumbnail_scene_id": 1,
    }


def generate_scene_video_with_veo(
    image_path: Path,
    visual_prompt: str,
    raw_veo_mp4: Path,
    out_segment: Path,
    duration_sec: float,
    fps: int,
    veo_model: str,
) -> None:
    """สร้างวิดีโอเคลื่อนไหวจากภาพประกอบของ Nano Banana ด้วย Vertex AI Veo แล้วตัดให้ตรงความยาวเสียงของฉาก"""
    from google.genai import types

    if not raw_veo_mp4.exists():
        client = get_genai_client()
        motion_prompt = (
            f"Smooth gentle 2D vector animation, subtle character movement, clean flat illustration style, "
            f"no text, no morphing: {visual_prompt}"
        )
        operation = client.models.generate_videos(
            model=veo_model,
            source=types.GenerateVideosSource(
                prompt=motion_prompt,
                image=types.Image.from_file(location=str(image_path)),
            ),
            config=types.GenerateVideosConfig(
                aspect_ratio="9:16",
                number_of_videos=1,
                duration_seconds=4,
                generate_audio=False,
            ),
        )
        while not operation.done:
            time.sleep(6)
            operation = client.operations.get(operation)

        resp = getattr(operation, "response", None) or getattr(operation, "result", None)
        gen_videos = getattr(resp, "generated_videos", None) or []
        if not gen_videos:
            raise RuntimeError(f"Veo ไม่ได้ส่งไฟล์วิดีโอกลับมาสำหรับ {image_path.name}")

        video_obj = gen_videos[0].video
        video_bytes = getattr(video_obj, "video_bytes", None)
        if video_bytes:
            raw_veo_mp4.write_bytes(video_bytes)
        else:
            client.files.download(file=video_obj)
            video_obj.save(str(raw_veo_mp4))

    # Trim or loop Veo output to match exact scene audio duration_sec at 1080x1920 30fps
    cmd = [
        get_ffmpeg_bin(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(raw_veo_mp4),
        "-vf",
        f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps={fps}",
        "-t",
        f"{duration_sec:.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "fast",
        "-crf",
        "20",
        str(out_segment),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def render_scene_clip_ken_burns(
    image_path: Path,
    out_segment: Path,
    duration_sec: float,
    fps: int,
    zoom_in: bool,
) -> None:
    frames = max(1, int(round(duration_sec * fps)))
    if zoom_in:
        zp = (
            f"scale=1200:2134,"
            f"zoompan=z='min(zoom+0.0012,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s=1080x1920:fps={fps}"
        )
    else:
        zp = (
            f"scale=1200:2134,"
            f"zoompan=z='if(eq(on,1),1.12,max(1.0,zoom-0.0012))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s=1080x1920:fps={fps}"
        )

    cmd = [
        get_ffmpeg_bin(),
        "-y",
        "-loop",
        "1",
        "-i",
        str(image_path),
        "-vf",
        zp,
        "-t",
        f"{duration_sec:.3f}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "ultrafast",
        "-crf",
        "20",
        str(out_segment),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def find_bgm_file() -> Path | None:
    bgm_dir = ASSETS_DIR / "bgm"
    if not bgm_dir.exists():
        return None
    for ext in ("*.mp3", "*.wav", "*.m4a"):
        matches = list(bgm_dir.glob(ext))
        if matches:
            return matches[0]
    return None


def generate_metadata(clip_path: Path, mock: bool = False) -> dict[str, Any]:
    script_data = json.loads((clip_path / "script.json").read_text(encoding="utf-8"))
    factcheck_file = clip_path / "factcheck.json"
    factcheck_data = (
        json.loads(factcheck_file.read_text(encoding="utf-8"))
        if factcheck_file.exists()
        else {}
    )
    prompt = render_prompt(
        "05_metadata.md",
        script=json.dumps(script_data, ensure_ascii=False),
        factcheck=json.dumps(factcheck_data, ensure_ascii=False),
    )
    meta = call_llm_json(
        prompt,
        mock_response=build_mock_metadata(script_data, factcheck_data),
        force_mock=mock,
    )
    yt = meta.setdefault("youtube", {})
    desc = yt.get("description", "")
    if "คลิปนี้สร้างด้วยความช่วยเหลือของ AI" not in desc:
        yt["description"] = desc.rstrip() + "\nคลิปนี้สร้างด้วยความช่วยเหลือของ AI"
    tt = meta.setdefault("tiktok", {})
    tt["ai_label"] = True

    (clip_path / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def run_render(clip_dir: str | Path, mock: bool = False) -> Path:
    clip_path = resolve_clip_dir(clip_dir)
    manifest_file = clip_path / "audio" / "manifest.json"
    subs_file = clip_path / "subs.ass"
    script_file = clip_path / "script.json"

    if not manifest_file.exists():
        raise FileNotFoundError(f"ไม่พบ {manifest_file} กรุณารัน 04_tts.py ก่อน")
    if not subs_file.exists():
        raise FileNotFoundError(f"ไม่พบ {subs_file} กรุณารัน 06_subtitles.py ก่อน")

    channel_cfg = load_yaml("channel.yaml")
    video_cfg = channel_cfg.get("video", {})
    fps = int(video_cfg.get("fps", 30))
    bgm_ratio = float(channel_cfg.get("audio", {}).get("bgm_volume_ratio", 0.12))

    motion_mode = (
        "ken_burns"
        if mock
        else (os.getenv("VIDEO_MOTION_MODE") or video_cfg.get("motion_mode", "veo")).lower()
    )
    veo_model = os.getenv("VEO_MODEL") or video_cfg.get("veo_model", "veo-3.1-fast-generate-001")

    script_data = json.loads(script_file.read_text(encoding="utf-8")) if script_file.exists() else {}
    visual_by_id = {
        int(s.get("id", idx)): s.get("visual", "")
        for idx, s in enumerate(script_data.get("scenes", []), start=1)
    }

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    temp_dir = clip_path / "segments"
    veo_dir = clip_path / "veo_clips"
    temp_dir.mkdir(parents=True, exist_ok=True)
    if motion_mode in ("veo", "veo_hook_only"):
        veo_dir.mkdir(parents=True, exist_ok=True)

    scenes_manifest = manifest.get("scenes", [])
    total_scenes = len(scenes_manifest)

    def _process_scene(args_tuple: tuple[int, dict[str, Any]]) -> Path:
        idx, scene_info = args_tuple
        sid = int(scene_info["scene_id"])
        dur = float(scene_info["duration_sec"])
        img_path = clip_path / "images" / f"scene_{sid:02d}.png"
        if not img_path.exists():
            raise FileNotFoundError(f"ไม่พบภาพฉาก {img_path} กรุณารัน 05_images.py ก่อน")

        seg_path = temp_dir / f"seg_{sid:02d}.mp4"
        use_veo = motion_mode == "veo" or (
            motion_mode == "veo_hook_only" and idx in (1, 4)
        )
        if use_veo:
            raw_veo = veo_dir / f"veo_{sid:02d}.mp4"
            print(
                f"[07_render] กำลังสร้างวิดีโอ Veo ฉากที่ {idx}/{total_scenes} ({raw_veo.name})...",
                flush=True,
            )
            try:
                generate_scene_video_with_veo(
                    image_path=img_path,
                    visual_prompt=visual_by_id.get(sid, ""),
                    raw_veo_mp4=raw_veo,
                    out_segment=seg_path,
                    duration_sec=dur,
                    fps=fps,
                    veo_model=veo_model,
                )
            except Exception as exc:
                print(
                    f"[07_render] Veo ฉากที่ {sid} ขัดข้อง ({exc}) สลับใช้ Ken Burns สำหรับฉากนี้",
                    flush=True,
                )
                render_scene_clip_ken_burns(
                    image_path=img_path,
                    out_segment=seg_path,
                    duration_sec=dur,
                    fps=fps,
                    zoom_in=(idx % 2 == 1),
                )
        else:
            render_scene_clip_ken_burns(
                image_path=img_path,
                out_segment=seg_path,
                duration_sec=dur,
                fps=fps,
                zoom_in=(idx % 2 == 1),
            )
        return seg_path

    workers = 3 if motion_mode == "veo" else 4
    with ThreadPoolExecutor(max_workers=workers) as pool:
        segment_files = list(pool.map(_process_scene, enumerate(scenes_manifest, start=1)))

    concat_list = temp_dir / "concat.txt"
    concat_lines = [f"file '{seg.name}'" for seg in segment_files]
    concat_list.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

    ffmpeg_bin = get_ffmpeg_bin()
    merged_video = temp_dir / "merged_video.mp4"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            str(merged_video),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    bgm_file = find_bgm_file()
    final_mp4 = clip_path / "final.mp4"

    if bgm_file:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            "segments/merged_video.mp4",
            "-i",
            "audio/narration.wav",
            "-stream_loop",
            "-1",
            "-i",
            str(bgm_file.resolve()),
            "-filter_complex",
            f"[0:v]ass=subs.ass[v];[1:a]volume=1.0[a1];[2:a]volume={bgm_ratio}[a2];[a1][a2]amix=inputs=2:duration=first:dropout_transition=2[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "final.mp4",
        ]
    else:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i",
            "segments/merged_video.mp4",
            "-i",
            "audio/narration.wav",
            "-vf",
            "ass=subs.ass",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "final.mp4",
        ]

    subprocess.run(
        cmd,
        cwd=str(clip_path),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for f in segment_files:
        f.unlink(missing_ok=True)
    concat_list.unlink(missing_ok=True)
    merged_video.unlink(missing_ok=True)
    try:
        temp_dir.rmdir()
    except OSError:
        pass

    generate_metadata(clip_path, mock=mock)
    update_status(
        clip_path,
        "rendered",
        note=f"เรนเดอร์ final.mp4 (motion={motion_mode}) และสร้าง meta.json สำเร็จ",
    )
    print(f"[07_render] สร้างวิดีโอ {final_mp4} (motion={motion_mode}) สำเร็จ")
    return final_mp4


def main() -> None:
    parser = argparse.ArgumentParser(description="07: เรนเดอร์วิดีโอด้วย Veo / FFmpeg และสร้าง meta.json")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="ใช้โหมดจำลองสำหรับเรนเดอร์และสร้าง meta.json")
    args = parser.parse_args()
    run_render(args.clip, mock=args.mock)


if __name__ == "__main__":
    main()
