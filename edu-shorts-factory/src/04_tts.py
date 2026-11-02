from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.paths import get_ffmpeg_bin, load_yaml, resolve_clip_dir
from utils.status import read_status


def generate_tone_wav(output_path: Path, duration_sec: float, freq: float = 440.0) -> None:
    sample_rate = 44100
    num_samples = max(int(sample_rate * duration_sec), sample_rate)
    with wave.open(str(output_path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_samples):
            t = i / sample_rate
            envelope = min(t / 0.05, 1.0, (duration_sec - t) / 0.05)
            val = int(32767 * 0.15 * max(0.0, envelope) * math.sin(2 * math.pi * freq * t))
            frames.extend(struct.pack("<h", val))
        wav_file.writeframes(bytes(frames))


def estimate_thai_speech_duration(text: str, speed: float = 1.1) -> float:
    char_count = len(text.strip())
    raw_sec = max(2.2, min(4.0, (char_count / 14.5) / max(speed, 0.8)))
    return round(raw_sec, 2)


async def synth_edge_tts(text: str, out_mp3: Path, voice: str, rate: str, pitch: str) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(out_mp3))


def synth_tokenme_tts(
    text: str,
    out_mp3: Path,
    voices_cfg: dict[str, Any],
) -> None:
    from openai import OpenAI

    cfg = voices_cfg.get("providers", {}).get("tokenme", {})
    api_key = os.getenv("TOKENME_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ไม่พบ TOKENME_API_KEY ใน .env")

    base_url = os.getenv("TOKENME_BASE_URL") or cfg.get(
        "base_url", "https://api.tokenme.limited/api/v1"
    )
    user_agent = os.getenv("TOKENME_USER_AGENT") or cfg.get(
        "user_agent", "edu-shorts-factory/1.0"
    )
    model = os.getenv("TOKENME_MODEL") or cfg.get("model", "paxa/paxa-tts-flash-v2")
    voice = os.getenv("TOKENME_VOICE") or cfg.get("voice", "bualoi")
    response_format = cfg.get("response_format", "mp3")

    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        default_headers={"User-Agent": user_agent},
    )

    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        response_format=response_format,
    ) as response:
        response.stream_to_file(str(out_mp3))


def convert_to_wav_and_trim(
    input_audio: Path,
    output_wav: Path,
    trim_silence: bool = True,
    threshold_db: int = -35,
    speed: float = 1.12,
) -> None:
    af_filters = []
    if trim_silence:
        af_filters.append(
            f"silenceremove=start_periods=1:start_silence=0.02:start_threshold={threshold_db}dB,"
            f"areverse,silenceremove=start_periods=1:start_silence=0.03:start_threshold={threshold_db}dB,areverse"
        )
    if abs(speed - 1.0) > 0.01:
        clamped = max(0.5, min(2.0, speed))
        af_filters.append(f"atempo={clamped:.2f}")
    cmd = [get_ffmpeg_bin(), "-y", "-i", str(input_audio)]
    if af_filters:
        cmd.extend(["-af", ",".join(af_filters)])
    cmd.extend(["-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(output_wav)])
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_wav_duration(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return round(frames / float(rate), 3)


def concat_wav_files(wav_files: list[Path], output_wav: Path) -> None:
    if not wav_files:
        raise ValueError("ไม่มีไฟล์เสียงสำหรับนำมารวม")
    with wave.open(str(output_wav), "wb") as out_wf:
        for idx, fpath in enumerate(wav_files):
            with wave.open(str(fpath), "rb") as in_wf:
                if idx == 0:
                    out_wf.setparams(in_wf.getparams())
                out_wf.writeframes(in_wf.readframes(in_wf.getnframes()))


def synth_scene_audio(
    text: str,
    scene_idx: int,
    scene_wav: Path,
    voices_cfg: dict[str, Any],
    provider: str,
    mock: bool = False,
) -> None:
    speed = float(voices_cfg.get("speed", 1.1))
    trim_silence = bool(voices_cfg.get("trim_silence", True))
    threshold_db = int(voices_cfg.get("silence_threshold_db", -40))

    if mock:
        dur = estimate_thai_speech_duration(text, speed=speed)
        generate_tone_wav(scene_wav, duration_sec=dur, freq=320.0 + scene_idx * 25.0)
        return

    if provider == "tokenme":
        tmp_mp3 = scene_wav.with_suffix(".mp3")
        try:
            synth_tokenme_tts(text, tmp_mp3, voices_cfg)
            convert_to_wav_and_trim(tmp_mp3, scene_wav, trim_silence, threshold_db, speed=speed)
            tmp_mp3.unlink(missing_ok=True)
            return
        except Exception as exc:
            tmp_mp3.unlink(missing_ok=True)
            raise RuntimeError(f"TokenMe TTS ล้มเหลวในฉากที่ {scene_idx}: {exc}") from exc

    if provider == "edge_tts":
        cfg = voices_cfg.get("providers", {}).get("edge_tts", {})
        voice = cfg.get("voice", "th-TH-PremwadeeNeural")
        rate = cfg.get("rate", "+10%")
        pitch = cfg.get("pitch", "+0Hz")
        tmp_mp3 = scene_wav.with_suffix(".mp3")
        try:
            asyncio.run(synth_edge_tts(text, tmp_mp3, voice, rate, pitch))
            convert_to_wav_and_trim(tmp_mp3, scene_wav, trim_silence, threshold_db)
            tmp_mp3.unlink(missing_ok=True)
            return
        except Exception as exc:
            tmp_mp3.unlink(missing_ok=True)
            print(f"[04_tts] Edge-TTS ขัดข้อง ({exc}) สลับใช้โทนเสียงจำลองตามความยาวคำ")
            dur = estimate_thai_speech_duration(text, speed=speed)
            generate_tone_wav(scene_wav, duration_sec=dur, freq=320.0 + scene_idx * 25.0)
            return

    if provider == "botnoi":
        api_key = os.getenv("BOTNOI_API_KEY", "")
        if not api_key:
            raise RuntimeError("ไม่พบ BOTNOI_API_KEY ใน .env")
        cfg = voices_cfg.get("providers", {}).get("botnoi", {})
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api-voice.botnoi.ai/openapi/v1/generate_audio",
                headers={"Botnoi-Token": api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "speaker": str(cfg.get("speaker_id", "1")),
                    "volume": float(cfg.get("volume", 1.0)),
                    "speed": float(cfg.get("speed", speed)),
                    "type_media": "wav",
                    "save_file": "true",
                },
            )
            resp.raise_for_status()
            audio_url = resp.json().get("audio_url")
            audio_resp = client.get(audio_url)
            audio_resp.raise_for_status()
            raw_wav = scene_wav.with_name(f"{scene_wav.stem}_raw.wav")
            raw_wav.write_bytes(audio_resp.content)
            convert_to_wav_and_trim(raw_wav, scene_wav, trim_silence, threshold_db)
            raw_wav.unlink(missing_ok=True)
            return

    if provider == "elevenlabs":
        api_key = os.getenv("ELEVENLABS_API_KEY", "")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")
        if not api_key or not voice_id:
            raise RuntimeError("ไม่พบ ELEVENLABS_API_KEY หรือ ELEVENLABS_VOICE_ID ใน .env")
        cfg = voices_cfg.get("providers", {}).get("elevenlabs", {})
        tmp_mp3 = scene_wav.with_suffix(".mp3")
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "text": text,
                    "model_id": cfg.get("model_id", "eleven_multilingual_v2"),
                    "voice_settings": {
                        "stability": cfg.get("stability", 0.55),
                        "similarity_boost": cfg.get("similarity_boost", 0.75),
                        "style": cfg.get("style", 0.15),
                    },
                },
            )
            resp.raise_for_status()
            tmp_mp3.write_bytes(resp.content)
            convert_to_wav_and_trim(tmp_mp3, scene_wav, trim_silence, threshold_db)
            tmp_mp3.unlink(missing_ok=True)
            return

    dur = estimate_thai_speech_duration(text, speed=speed)
    generate_tone_wav(scene_wav, duration_sec=dur, freq=320.0 + scene_idx * 25.0)


def run_tts(clip_dir: str | Path, mock: bool = False) -> dict[str, Any]:
    clip_path = resolve_clip_dir(clip_dir)
    st = read_status(clip_path)
    if st.get("status") == "failed_factcheck":
        raise RuntimeError("คลิปนี้ไม่ผ่าน Fact-check ห้ามสร้างเสียงต่อจนกว่าจะแก้ไขผ่าน")

    script_file = clip_path / "script.json"
    if not script_file.exists():
        raise FileNotFoundError(f"ไม่พบ {script_file}")

    script_data = json.loads(script_file.read_text(encoding="utf-8"))
    voices_cfg = load_yaml("voices.yaml")
    provider = os.getenv("TTS_PROVIDER") or voices_cfg.get("default_provider", "tokenme")

    audio_dir = clip_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    scene_wavs: list[Path] = []
    manifest_scenes: list[dict[str, Any]] = []
    cursor_sec = 0.0

    for idx, scene in enumerate(script_data.get("scenes", []), start=1):
        sid = int(scene.get("id", idx))
        narration = scene.get("narration", "").strip()
        scene_wav = audio_dir / f"scene_{sid:02d}.wav"

        synth_scene_audio(
            text=narration,
            scene_idx=sid,
            scene_wav=scene_wav,
            voices_cfg=voices_cfg,
            provider=provider,
            mock=mock,
        )

        dur = get_wav_duration(scene_wav)
        start_sec = round(cursor_sec, 3)
        end_sec = round(cursor_sec + dur, 3)
        cursor_sec = end_sec

        scene_wavs.append(scene_wav)
        manifest_scenes.append(
            {
                "scene_id": sid,
                "file": scene_wav.name,
                "narration": narration,
                "duration_sec": dur,
                "start_sec": start_sec,
                "end_sec": end_sec,
            }
        )

    narration_wav = audio_dir / "narration.wav"
    concat_wav_files(scene_wavs, narration_wav)

    manifest = {
        "provider": "mock" if mock else provider,
        "total_duration_sec": round(cursor_sec, 3),
        "narration_file": narration_wav.name,
        "scenes": manifest_scenes,
    }
    (audio_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"[04_tts] สร้างไฟล์เสียงครบ {len(scene_wavs)} ฉาก (provider={manifest['provider']}) ความยาวรวม {manifest['total_duration_sec']:.2f} วินาที"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="04: สร้างเสียงพากย์แยกตามฉากและรวมเป็น narration.wav")
    parser.add_argument("--clip", type=str, required=True, help="โฟลเดอร์คลิปใน output/")
    parser.add_argument("--mock", action="store_true", help="สร้างไฟล์เสียงทดสอบโดยไม่เรียก API")
    args = parser.parse_args()
    run_tts(args.clip, mock=args.mock)


if __name__ == "__main__":
    main()
