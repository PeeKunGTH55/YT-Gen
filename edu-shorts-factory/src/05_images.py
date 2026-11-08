from __future__ import annotations

import argparse
import base64
from io import BytesIO
import json
import os
import sys
from pathlib import Path
from typing import Any
import httpx
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.llm import call_llm_json, get_genai_client
from utils.paths import ASSETS_DIR, parse_style_guide, render_prompt, resolve_clip_dir
from utils.status import update_status


def create_vector_placeholder_image(output_png: Path, scene_id: int) -> None:
    """สร้างภาพประกอบสไตล์ Flat Vector 9:16 ไร้ตัวอักษร สำหรับโหมดทดสอบ"""
    width, height = 1080, 1920
    bg_colors = [
        (234, 244, 248),
        (253, 251, 247),
        (232, 245, 233),
        (255, 248, 225),
    ]
    bg = bg_colors[(scene_id - 1) % len(bg_colors)]
    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)

    cx, cy = width // 2, 760
    radius = 260 + (scene_id % 3) * 25
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=(255, 255, 255),
        outline=(29, 53, 87),
        width=8,
    )

    sun_x = 360 + (scene_id * 35) % 360
    sun_y = 480 + (scene_id * 25) % 160
    draw.ellipse(
        (sun_x - 85, sun_y - 85, sun_x + 85, sun_y + 85),
        fill=(255, 183, 3),
        outline=(29, 53, 87),
        width=8,
    )

    char_y = 900
    draw.rounded_rectangle(
        (cx - 130, char_y, cx + 130, char_y + 260),
        radius=50,
        fill=(255, 183, 3),
        outline=(29, 53, 87),
        width=8,
    )
    draw.ellipse(
        (cx - 110, char_y - 200, cx + 110, char_y + 10),
        fill=(255, 229, 180),
        outline=(29, 53, 87),
        width=8,
    )
    draw.ellipse(
        (cx - 75, char_y - 125, cx - 15, char_y - 65),
        outline=(29, 53, 87),
        width=7,
    )
    draw.ellipse(
        (cx + 15, char_y - 125, cx + 75, char_y - 65),
        outline=(29, 53, 87),
        width=7,
    )
    draw.line((cx - 15, char_y - 95, cx + 15, char_y - 95), fill=(29, 53, 87), width=7)

    img.save(output_png, format="PNG")


def generate_via_nano_banana(
    prompt: str,
    output_png: Path,
    ref_image_path: Path | None,
) -> None:
    """เจนภาพด้วย Nano Banana (gemini-2.5-flash-image / gemini-3-pro-image-preview) บน Vertex AI"""
    import time
    from google.genai import types

    client = get_genai_client()
    model = os.getenv("NANO_BANANA_MODEL", "gemini-2.5-flash-image")

    contents: list[Any] = []
    if ref_image_path and ref_image_path.exists():
        ref_pil = Image.open(ref_image_path)
        contents.append(ref_pil)
        contents.append(
            f"Keep the exact same character design, proportions, glasses, and yellow hoodie from this reference image. {prompt}"
        )
    else:
        contents.append(prompt)

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio="9:16",
                    ),
                ),
            )

            candidates = getattr(resp, "candidates", None) or []
            for cand in candidates:
                content = getattr(cand, "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and getattr(inline_data, "data", None):
                        img = Image.open(BytesIO(inline_data.data)).convert("RGB")
                        if img.size != (1080, 1920):
                            img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
                        img.save(output_png, format="PNG")
                        return

            raise RuntimeError("Nano Banana ไม่ได้ส่งข้อมูลภาพกลับมาใน response")
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_retries:
                wait_sec = 8 * (attempt + 1)
                print(f"[05_images] ⚠️ ชน Rate Limit (429 RESOURCE_EXHAUSTED) รอ {wait_sec} วินาทีแล้วลองใหม่ (รอบที่ {attempt+1}/{max_retries})...", flush=True)
                time.sleep(wait_sec)
                continue
            raise


def generate_via_fal(prompt: str, output_png: Path, ref_image_path: Path | None) -> None:
    fal_key = os.getenv("FAL_KEY", "")
    if not fal_key:
        raise RuntimeError("ไม่พบ FAL_KEY ใน .env")

    model = os.getenv("FAL_MODEL", "fal-ai/flux/schnell")
    payload: dict[str, Any] = {
        "prompt": prompt,
        "image_size": "portrait_16_9",
        "num_images": 1,
    }

    if ref_image_path and ref_image_path.exists() and "kontext" in model:
        b64 = base64.b64encode(ref_image_path.read_bytes()).decode("ascii")
        payload["image_url"] = f"data:image/png;base64,{b64}"

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"https://fal.run/{model}",
            headers={"Authorization": f"Key {fal_key}", "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        images = resp.json().get("images", [])
        if not images:
            raise RuntimeError("fal.ai ไม่ได้ส่ง URL ภาพกลับมา")
        img_url = images[0]["url"]
        img_resp = client.get(img_url)
        img_resp.raise_for_status()
        output_png.write_bytes(img_resp.content)


def build_scene_image_prompt(
    scene_visual: str,
    style_prefix: str,
    character_description: str,
    mock: bool,
) -> str:
    return (
        f"Vertical 9:16 illustration, main subject centered in the middle 60% of the frame, "
        f"keep top 10% and bottom 25% mostly empty background. "
        f"Character: {character_description}. "
        f"Scene action: {scene_visual}. "
        f"Style: {style_prefix}, no text, no letters, no numbers, no watermark, no realistic human faces."
    )


def run_images(clip_dir: str | Path, mock: bool = False) -> list[Path]:
    clip_path = resolve_clip_dir(clip_dir)
    script_file = clip_path / "script.json"
    if not script_file.exists():
        raise FileNotFoundError(f"ไม่พบ {script_file}")

    script_data = json.loads(script_file.read_text(encoding="utf-8"))
    style_info = parse_style_guide()

    image_provider = (
        "placeholder" if mock else os.getenv("IMAGE_PROVIDER", "nano_banana").lower()
    )
    ref_image = ASSETS_DIR / "character_ref.png"
    images_dir = clip_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    prompts_log: list[dict[str, Any]] = []
    generated_files: list[Path] = []

    scenes = script_data.get("scenes", [])
    total_scenes = len(scenes)
    for idx, scene in enumerate(scenes, start=1):
        sid = int(scene.get("id", idx))
        visual_desc = scene.get("visual", "")
        full_prompt = build_scene_image_prompt(
            scene_visual=visual_desc,
            style_prefix=style_info["style_prefix"],
            character_description=style_info["character_description"],
            mock=mock,
        )
        out_png = images_dir / f"scene_{sid:02d}.png"
        if out_png.exists() and out_png.stat().st_size > 10_000:
            print(f"[05_images] พบภาพฉากที่ {idx}/{total_scenes} ({out_png.name}) อยู่แล้ว ข้ามการสร้างใหม่...", flush=True)
            prompts_log.append(
                {
                    "scene_id": sid,
                    "file": out_png.name,
                    "provider": image_provider,
                    "visual": visual_desc,
                    "image_prompt": full_prompt,
                    "cached": True,
                }
            )
            generated_files.append(out_png)
            continue

        print(f"[05_images] กำลังสร้างภาพฉากที่ {idx}/{total_scenes} ({out_png.name})...", flush=True)

        if image_provider == "nano_banana":
            generate_via_nano_banana(
                full_prompt, out_png, ref_image if ref_image.exists() else None
            )
        elif image_provider == "fal":
            generate_via_fal(
                full_prompt, out_png, ref_image if ref_image.exists() else None
            )
        else:
            create_vector_placeholder_image(out_png, sid)

        prompts_log.append(
            {
                "scene_id": sid,
                "file": out_png.name,
                "provider": image_provider,
                "visual": visual_desc,
                "image_prompt": full_prompt,
            }
        )
        generated_files.append(out_png)
        # หน่วงเวลาเล็กน้อยเพื่อป้องกันการชน Burst RPM Limit ของ Vertex AI
        import time
        time.sleep(2)

    (images_dir / "prompts.json").write_text(
        json.dumps(prompts_log, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if (clip_path / "audio" / "manifest.json").exists():
        update_status(
            clip_path,
            "assets_ready",
            note=f"เตรียมไฟล์เสียงและภาพประกอบครบ {len(generated_files)} ฉาก (provider={image_provider})",
        )
    print(f"[05_images] สร้างภาพประกอบครบ {len(generated_files)} ฉาก (provider={image_provider}) ใน {images_dir}")
    return generated_files


def overlay_thai_headline_on_thumbnail(
    img_path: Path, headline: str, out_png: Path, out_jpg: Path
) -> None:
    img = Image.open(img_path).convert("RGBA")
    width, height = img.size
    text = (headline or "").strip()

    if text:
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        font_paths = [
            ASSETS_DIR / "fonts" / "Kanit-Black.ttf",
            ASSETS_DIR / "fonts" / "Kanit-Bold.ttf",
            Path("C:/Windows/Fonts/tahomabd.ttf"),
            Path("C:/Windows/Fonts/tahoma.ttf"),
            Path("C:/Windows/Fonts/leelawdb.ttf"),
        ]
        font = None
        for fp in font_paths:
            if fp.exists():
                try:
                    font = ImageFont.truetype(str(fp), 96)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (width - tw) // 2
        ty = 230

        pad_x, pad_y = 52, 28
        box_rect = (tx - pad_x, ty - pad_y, tx + tw + pad_x, ty + th + pad_y)

        # 1. 3D Drop shadow for badge
        draw.rounded_rectangle(
            (box_rect[0] + 6, box_rect[1] + 10, box_rect[2] + 6, box_rect[3] + 10),
            radius=36,
            fill=(0, 0, 0, 160),
        )
        # 2. Energetic badge (Crimson Red with Bright Gold Border)
        draw.rounded_rectangle(
            box_rect,
            radius=36,
            fill=(220, 20, 60, 245),
            outline=(255, 215, 0, 255),
            width=9,
        )
        # 3. 3D Text Outline/Shadow
        for ox, oy in [
            (-3, -3),
            (3, -3),
            (-3, 3),
            (3, 3),
            (0, 5),
            (0, -4),
            (-4, 0),
            (4, 0),
        ]:
            draw.text((tx + ox, ty + oy), text, font=font, fill=(0, 0, 0, 255))
        # 4. Main Bright Text
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255, 255))

        img = Image.alpha_composite(img, overlay)

    rgb = img.convert("RGB")
    rgb.save(out_png, format="PNG")
    rgb.save(out_jpg, format="JPEG", quality=95)


def generate_thumbnail(
    clip_dir: str | Path,
    visual_desc: str,
    headline: str,
    mock: bool = False,
) -> Path:
    clip_path = resolve_clip_dir(clip_dir)
    style_info = parse_style_guide()
    image_provider = (
        "placeholder" if mock else os.getenv("IMAGE_PROVIDER", "nano_banana").lower()
    )
    ref_image = ASSETS_DIR / "character_ref.png"

    thumb_prompt = (
        f"Extreme high-impact vertical 9:16 YouTube Shorts thumbnail illustration, highly detailed, "
        f"dramatic close-up of character {style_info['character_description']} with a shocked and intensely curious expression, "
        f"pointing with wide eyes at a large glowing {visual_desc}, "
        f"vibrant saturated warm colors, high contrast lighting, clean empty top area (Y 0 to 450) for title badge, "
        f"style: {style_info['style_prefix']}, no text, no letters, no numbers, no watermark."
    )

    raw_png = clip_path / "thumbnail_raw.png"
    out_png = clip_path / "thumbnail.png"
    out_jpg = clip_path / "thumbnail.jpg"

    print(f"[05_images] กำลังสร้างภาพปก Thumbnail (provider={image_provider})...", flush=True)
    if image_provider == "nano_banana":
        try:
            generate_via_nano_banana(
                thumb_prompt, raw_png, ref_image if ref_image.exists() else None
            )
        except Exception as exc:
            print(f"[05_images] Nano Banana Thumbnail ขัดข้อง ({exc}) ใช้ภาพฉากที่ 1 แทน")
            scene1 = clip_path / "images" / "scene_01.png"
            if scene1.exists():
                raw_png.write_bytes(scene1.read_bytes())
            else:
                create_vector_placeholder_image(raw_png, 1)
    elif image_provider == "fal":
        generate_via_fal(
            thumb_prompt, raw_png, ref_image if ref_image.exists() else None
        )
    else:
        scene1 = clip_path / "images" / "scene_01.png"
        if scene1.exists():
            raw_png.write_bytes(scene1.read_bytes())
        else:
            create_vector_placeholder_image(raw_png, 1)

    overlay_thai_headline_on_thumbnail(raw_png, headline, out_png, out_jpg)
    raw_png.unlink(missing_ok=True)
    print(f"[05_images] สร้างภาพปก {out_png} และ {out_jpg} สำเร็จ", flush=True)
    return out_png


def main() -> None:
    parser = argparse.ArgumentParser(description="05: สร้างภาพประกอบ 9:16 ด้วย Nano Banana บน Vertex AI")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="สร้างภาพ Vector ทดสอบโดยไม่เรียก API")
    args = parser.parse_args()
    run_images(args.clip, mock=args.mock)


if __name__ == "__main__":
    main()
