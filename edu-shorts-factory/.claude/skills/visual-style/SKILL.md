---
name: visual-style
description: มาตรฐานสไตล์ภาพประกอบ ตัวละครหลัก พาเลตสี และการเขียน Image Prompt ให้คงที่ทั้งซีรีส์
---

# Skill: Visual Style & Character Consistency

## 1. โครงสร้างการประกอบ Image Prompt
ทุกฉากต้องแปลง `scene.visual` เป็น Prompt ภาษาอังกฤษ 1 ย่อหน้า โดยรวม 4 ส่วน:
1. **Composition & Safe Zone**: `Vertical 9:16 illustration, main subject centered in the middle 60% of the frame, clean empty background in the top 10% and bottom 25%.`
2. **Character Description** (จาก `config/style_guide.md`): ระบุรายละเอียดตัวละคร "Nong Roo" เหมือนเดิมทุกครั้งที่ปรากฏตัว
3. **Scene Action & Object**: คำอธิบายวัตถุหลักและท่าทางที่สื่อความหมายของฉากนั้นแบบเข้าใจง่าย
4. **Style Prefix & Negative Rules**: ต่อท้ายด้วย `style_prefix` จาก `config/style_guide.md` และย้ำ `no text, no letters, no numbers, no watermark, no realistic human faces.`

## 2. การล็อกหน้าตาตัวละครข้ามฉาก (Character Consistency)
- วางไฟล์ต้นแบบไว้ที่ `assets/character_ref.png`
- ในขั้น `05_images.py` หากตรวจพบไฟล์ `assets/character_ref.png` จะส่งผ่านพารามิเตอร์ `image_url` / Reference Image ของ `fal.ai` คู่กับ Prompt เพื่อให้เสื้อผ้า ทรงผม และสัดส่วนคงที่ทั้ง 8-12 ฉาก
