# Edu Shorts Factory

ระบบผลิตคลิปสั้นความรู้ภาษาไทย (YouTube Shorts / TikTok) แบบกึ่งอัตโนมัติ แยกการทำงานเป็น 9 ขั้นตอน ตั้งแต่คิดหัวข้อ เขียนบท ตรวจข้อเท็จจริง สร้างเสียงพากย์ เจนภาพประกอบ ทำซับไตเติลไทย ตัดต่อด้วย FFmpeg ส่งตรวจอนุมัติผ่าน Telegram จนถึงโพสต์ขึ้นแพลตฟอร์ม

## จุดเด่นสถาปัตยกรรม
- **1 คลิป = 1 โฟลเดอร์**: เก็บไฟล์ทุกขั้นไว้ใน `output/YYYY-MM-DD_<slug>/` พร้อม `status.json` ติดตามสถานะ
- **รันซ้ำเฉพาะขั้นที่พังได้**: แยกสคริปต์ `01_topics.py` ถึง `09_publish.py` อิสระต่อกัน
- **ซิงค์ภาพและเสียงระดับฉาก**: เจนเสียงแยกตามฉาก (`scene_01.wav`...) ทำให้รู้ความยาวแต่ละฉากแม่นยำสำหรับทำเอฟเฟกต์ Ken Burns และคำนวณเวลาซับไตเติลจากข้อความบทจริงใน `script.json` (ไม่เพี้ยนจาก STT)
- **Fact-Check อัตโนมัติพร้อม Auto-fix**: ตรวจทุกข้อเท็จจริงกับแหล่งอ้างอิงจริง หากพบจุดที่ต้องปรับ (`needs_edit`) ระบบแก้บทและตรวจซ้ำอัตโนมัติสูงสุด 2 รอบ
- **รองรับโหมดทดสอบ (`--mock`)**: ทดสอบรัน Pipeline ทั้งระบบได้ทันทีโดยไม่ต้องใช้ API Key เสียเงิน (ใช้ Edge-TTS / สังเคราะห์เสียงและภาพทดสอบพร้อมเรนเดอร์ `final.mp4` จริงด้วย FFmpeg)

## โครงสร้างโฟลเดอร์
```text
edu-shorts-factory/
├── CLAUDE.md                     # กติกาโปรเจกต์สำหรับ AI Agent
├── AGENTS.md                     # Symlink ชี้ไปที่ CLAUDE.md
├── README.md                     # คู่มือการใช้งานโปรเจกต์
├── requirements.txt              # แพ็กเกจ Python ที่ต้องใช้
├── .env.example                  # ตัวอย่างไฟล์ตั้งค่า API Keys
├── .claude/
│   └── skills/                   # Skills ทั้ง 8 ตัวสำหรับควบคุมมาตรฐานแต่ละขั้น
├── config/
│   ├── channel.yaml              # สเปกคลิป ภาษา กลุ่มเป้าหมาย เสียง และเวิร์กโฟลว์
│   ├── style_guide.md            # สไตล์ภาพ ตัวละครหลัก และพาเลตสี
│   ├── voices.yaml               # ตั้งค่าผู้ให้บริการ TTS และความเร็วเสียง
│   ├── formats.yaml              # รูปแบบการเล่าเรื่อง 6 สูตร และกฎการสลับใช้
│   └── safe_zones.yaml           # พิกัดพื้นที่ปลอดภัยของ Shorts / TikTok
├── prompts/
│   ├── 01_topic.md               # คิดหัวข้อใหม่ 10 หัวข้อตามหมวดและ format
│   ├── 02_script.md              # เขียนบท 8-12 ฉาก พร้อมระบุ claims
│   ├── 03_factcheck.md           # ตรวจสอบข้อเท็จจริงและความเหมาะสมของการเปรียบเทียบ
│   ├── 04_image.md               # แปลงคำอธิบายฉากเป็น Image Prompt ภาษาอังกฤษ
│   ├── 05_metadata.md            # สร้างชื่อคลิป คำอธิบาย แหล่งอ้างอิง และแฮชแท็ก
│   └── 06_hook_variants.md       # สร้างตัวเลือก Hook 5 สูตรก่อนเลือกตัวที่ดีที่สุด
├── data/
│   ├── topics.csv                # คลังหัวข้อ สถานะ และวันที่ผลิต
│   └── performance.csv           # สถิติยอดดูและ % ดูจบสำหรับใช้วิเคราะห์ปรับปรุง
├── src/
│   ├── pipeline.py               # ตัวรันรวมทุกขั้นแบบอัตโนมัติ
│   ├── 01_topics.py              # คิดหัวข้อและบันทึกลง data/topics.csv
│   ├── 02_script.py              # คัดเลือก Hook + เขียนบทลง script.json
│   ├── 03_factcheck.py           # ค้นข้อมูลตรวจบท + Auto-fix สูงสุด 2 รอบ
│   ├── 04_tts.py                 # สร้างเสียงพากย์แยกฉากและรวมไฟล์เสียงหลัก
│   ├── 05_images.py              # เจนภาพประกอบ 9:16 ครบทุกฉาก
│   ├── 06_subtitles.py           # ตัดคำไทยด้วย PyThaiNLP สร้างไฟล์ซับ subs.ass
│   ├── 07_render.py              # ประกอบวิดีโอ FFmpeg + สร้าง meta.json
│   ├── 08_review.py              # ส่งคลิปเข้า Telegram พร้อมปุ่ม Approve/Reject
│   ├── 09_publish.py             # อัปโหลด YouTube Shorts / TikTok / Export โพสต์มือ
│   └── utils/                    # paths.py, status.py, llm.py
├── output/                       # โฟลเดอร์ผลลัพธ์แยกตามคลิป
├── assets/                       # ฟอนต์ไทย เพลงประกอบ (BGM) และรูปอ้างอิงตัวละคร
└── logs/                         # บันทึกการทำงานของระบบ
```

## การติดตั้ง
1. สร้าง Virtual Environment และติดตั้งแพ็กเกจ:
   ```bash
   cd edu-shorts-factory
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. ติดตั้ง **FFmpeg** ให้เรียกใช้งานผ่าน `PATH` ได้ (`ffmpeg -version`)
3. คัดลอกไฟล์ `.env.example` เป็น `.env` แล้วใส่ API Keys ที่ต้องการใช้งาน:
   ```bash
   copy .env.example .env
   ```

## การใช้งาน
### 1. ทดสอบระบบครบวงจรทันที (Mock / Dry-Run Mode)
สร้างตั้งแต่หัวข้อ บท ตรวจข้อมูล เสียง ภาพ ซับ และเรนเดอร์ `final.mp4` จริงโดยไม่เสียค่า API:
```bash
python src/pipeline.py --topic-id 1 --mock
```

### 2. รันการผลิตจริงแบบอัตโนมัติ
```bash
# เลือกหัวข้อถัดไปที่สถานะเป็น idea ใน data/topics.csv มาผลิตจนถึงขั้นส่งตรวจ Telegram
python src/pipeline.py --auto

# รันเฉพาะคลิปที่ต้องการตั้งแต่ขั้นที่ค้างอยู่
python src/pipeline.py --clip output/2026-11-01_why-sky-blue
```

### 3. รันแยกแต่ละขั้น
```bash
python src/01_topics.py --category "วิทยาศาสตร์ใกล้ตัว"
python src/02_script.py --topic-id 1
python src/03_factcheck.py --clip output/2026-11-01_why-sky-blue
python src/04_tts.py --clip output/2026-11-01_why-sky-blue
python src/05_images.py --clip output/2026-11-01_why-sky-blue
python src/06_subtitles.py --clip output/2026-11-01_why-sky-blue
python src/07_render.py --clip output/2026-11-01_why-sky-blue
python src/08_review.py --clip output/2026-11-01_why-sky-blue --wait
python src/09_publish.py --clip output/2026-11-01_why-sky-blue
```

## สถานะใน `status.json`
`idea` -> `scripted` -> `factchecked` -> `assets_ready` -> `rendered` -> `awaiting_approval` -> `approved` -> `published`
(กรณีไม่ผ่านการตรวจ: `failed_factcheck` หรือ `rejected`)
