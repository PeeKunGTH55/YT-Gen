# CLAUDE.md — กติกาโปรเจกต์ Edu Shorts Factory

โปรเจกต์ผลิตคลิปสั้นความรู้ภาษาไทย (YouTube Shorts / TikTok) แบบกึ่งอัตโนมัติ (Semi-Automated Pipeline)

## 1. สถาปัตยกรรมและหลักการหลัก (Core Principles)
- **1 คลิป = 1 โฟลเดอร์**: ข้อมูลทุกอย่างของคลิปเก็บแยกใน `output/YYYY-MM-DD_<slug>/`
- **Idempotent & Modular**: แต่ละขั้นแยกสคริปต์ (`src/01_topics.py` ถึง `src/09_publish.py`) รันซ้ำเฉพาะขั้นที่พังได้โดยไม่กระทบขั้นก่อนหน้า
- **Human-in-the-Loop**: มีจุดอนุมัติผ่าน Telegram (`08_review.py`) ก่อนโพสต์จริง เมื่อระบบเสถียรแล้วปลด `workflow.require_approval: false` ใน `config/channel.yaml` ได้
- **State Machine (`status.json`)**:
  ```
  idea → scripted → factchecked → assets_ready → rendered → awaiting_approval → approved → published
  ```
  (สถานะกรณีไม่ผ่าน: `failed_factcheck`, `rejected`)

## 2. กฎเหล็กด้านเนื้อหาและคุณภาพ (Content & Quality Rules)
1. **กลุ่มเป้าหมาย**: ทุกวัย (เด็ก 8 ขวบถึงผู้สูงอายุเข้าใจได้) ภาษาพูด เรียบง่าย ไม่เว่อร์
2. **ความยาวและโครงสร้างบท**:
   - ความยาวพากย์ 25-45 วินาที (เพดานสูงสุดไม่เกิน 60 วินาที) ประมาณ 80-120 คำ
   - 8-12 ฉาก ฉากละ 2-4 วินาที ภาพเปลี่ยนทุกฉาก
   - **Hook 2 วินาทีแรก**: ประโยคแรกต้องเป็นคำถามหรือข้อเท็จจริงที่หยุดนิ้วทันที ห้ามทักทาย ห้ามแนะนำตัว ห้ามขึ้นต้นว่า "วันนี้เรามาดู..."
   - **Analogy**: ต้องเปรียบเทียบกับสิ่งใกล้ตัวอย่างน้อย 1 อย่างโดยไม่บิดเบือนหลักวิชาการ
   - **Loop Ending**: ประโยคสุดท้ายต้องเชื่อมกลับไปหาประโยคเปิด (Hook) เพื่อให้คลิปวนลูปเนียน
   - **No Call-to-Action / Clickbait**: ห้ามขอให้กดไลก์/ติดตามในบทพากย์ ห้ามใส่ตัวเลข วันที่ หรือชื่อบุคคลหากไม่มั่นใจ 100%
3. **การตรวจสอบข้อเท็จจริง (Fact-Check)**:
   - ห้ามข้ามขั้น `03_factcheck.py` เด็ดขาด
   - ทุก `claim` ใน `script.json` ต้องตรวจกับแหล่งอ้างอิงระดับสากล/หน่วยงานรัฐ/วิชาการ และต้องเปิดอ่านหน้าเว็บจริง ห้ามเดา URL
   - หากผลเป็น `needs_edit` ระบบจะนำ `fix` ไปแก้บทและตรวจซ้ำสูงสุด 2 รอบ หากยังไม่ผ่านหรือได้ `reject` ต้องหยุดทันที
4. **ภาพและพื้นที่ปลอดภัย (Visual & Safe Zone)**:
   - อัตราส่วน 9:16 (`1080x1920`, `30fps`, `h264`/`aac`)
   - วัตถุหลักและตัวละครอยู่กลาง 60% ของเฟรม เว้นว่างด้านบน 10% ด้านล่าง 25% และด้านขวา 15%
   - ห้ามมีตัวอักษร ตัวเลข โลโก้แบรนด์ หรือบุคคลจริงในภาพประกอบ
   - ใช้สไตล์ภาพจาก `config/style_guide.md` และส่งรูปอ้างอิง `assets/character_ref.png` เมื่อต้องการคุมตัวละครให้คงที่ทุกฉาก
5. **เสียงและซับไตเติล (Audio & Subtitles)**:
   - เจนเสียงแยกทีละฉาก (`audio/scene_01.wav`...) เพื่อให้เวลาเปลี่ยนภาพตรงกับเสียงพากย์แต่ละฉาก 100%
   - ซับไตเติล (`subs.ass`) ต้องใช้ข้อความที่ถูกต้องจาก `script.json` ตัดคำด้วย `PyThaiNLP` (3-6 คำต่อบรรทัด) เน้นสีคำสำคัญ (`emphasis_words`) และวางเหนือพื้นที่ปลอดภัยด้านล่าง
6. **การติดป้าย AI และลิขสิทธิ์**:
   - เปิด `ai_label: true` ทุกแพลตฟอร์ม และใส่ข้อความระบุการใช้ AI พร้อมแหล่งอ้างอิงในคำอธิบายคลิปเสมอ
   - เพลงประกอบ (`assets/bgm/`) ต้องเป็นเพลงที่มีสิทธิ์ใช้งานเชิงพาณิชย์เท่านั้น ความดัง `0.12` (10-15% ของเสียงพากย์)

## 3. คำสั่งรันงานหลัก (CLI Commands)
```bash
# รันครบทุกขั้นตั้งแต่สร้างหัวข้อจนส่งตรวจ (ใช้ --mock เพื่อทดสอบระบบโดยไม่เสียเครดิต API)
python src/pipeline.py --auto

# รันเฉพาะคลิปที่ระบุโฟลเดอร์
python src/pipeline.py --clip output/2026-11-01_why-sky-blue

# รันแยกทีละขั้น
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

## 4. รายการ Skills ใน `.claude/skills/`
เมื่อแก้โค้ดหรือสั่งสร้างเนื้อหาผ่าน Agent ให้ยึดกติกาใน Skill เหล่านี้:
- `script-writer`: โครงสร้าง JSON บทพากย์ กฎคำต้องห้าม และจังหวะการเล่าเรื่อง
- `shorts-hook`: สูตรสร้าง Hook 5 รูปแบบ และการเชื่อมประโยคจบแบบ Loop
- `fact-checker`: เกณฑ์แหล่งอ้างอิง ขั้นตอนค้นเว็บจริง และการตัดสิน claim
- `visual-style`: การคุมคาแรกเตอร์ พาเลตสี และการเขียน Image Prompt
- `safe-zone-layout`: พิกัด Safe Zone ของ YouTube Shorts และ TikTok
- `subtitle-thai`: การตัดคำภาษาไทยด้วย PyThaiNLP และการตั้งค่า `.ass`
- `video-render`: สูตร FFmpeg สำหรับ Ken Burns, Audio Ducking/Loudness และการฝังซับ
- `publish-checklist`: รายการตรวจทานขั้นสุดท้ายก่อนเผยแพร่สู่สาธารณะ
