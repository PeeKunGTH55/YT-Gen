---
name: video-render
description: สูตรประกอบวิดีโอด้วย FFmpeg สำหรับทำเอฟเฟกต์ Ken Burns ฝังซับไตเติล .ass และผสมเสียงพากย์กับเพลงประกอบ
---

# Skill: Video Render (FFmpeg Pipeline)

## 1. สเปกวิดีโอมาตรฐาน
- ความละเอียด: `1080x1920` (9:16), `30 fps`
- Video Codec: `libx264`, `-pix_fmt yuv420p`, `-crf 18`, `-preset medium`
- Audio Codec: `aac`, `192k`, `44100 Hz`

## 2. สูตร Ken Burns สลับฉาก (Zoom In / Zoom Out)
เพื่อไม่ให้ภาพนิ่งดูจืดชืด ขั้น `07_render.py` จะสลับทิศทางการซูมในแต่ละฉากตามความยาวเสียงจริงของฉากนั้น (`duration` วินาที, `frames = duration * 30`):
- **ฉากเลขคี่ (Slow Zoom In)**:
  ```text
  scale=2160:3840,zoompan=z='min(zoom+0.0012,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30
  ```
- **ฉากเลขคู่ (Slow Zoom Out)**:
  ```text
  scale=2160:3840,zoompan=z='if(eq(on,1),1.15,max(1.0,zoom-0.0012))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps=30
  ```

## 3. การฝังซับและการมิกซ์เสียง (Subtitles & Audio Mixing)
- ฝังซับไตเติลด้วยตัวกรอง `ass=filename='subs.ass'`
- เสียงพากย์หลัก (`narration.wav`) ปรับความดังให้สม่ำเสมอ
- หากมีไฟล์เพลงประกอบใน `assets/bgm/` ให้วนลูปและลดความดังด้วย `volume=0.12` (12% ของเสียงพากย์) แล้วรวมด้วย `amix=inputs=2:duration=first`
