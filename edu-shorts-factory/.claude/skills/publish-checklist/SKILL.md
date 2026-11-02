---
name: publish-checklist
description: รายการตรวจสอบขั้นสุดท้ายก่อนส่งอนุมัติและโพสต์ขึ้น YouTube Shorts / TikTok
---

# Skill: Publish Checklist (เช็กลิสต์ก่อนเผยแพร่)

ก่อนเปลี่ยนสถานะคลิปเป็น `approved` และรัน `09_publish.py` ระบบต้องตรวจสอบรายการต่อไปนี้ครบทุกข้อ:

1. **ความยาวและสเปกไฟล์ (`final.mp4`)**:
   - ความละเอียด `1080x1920`, อัตราเฟรม `30fps`
   - ความยาวรวมอยู่ในช่วง `25-45 วินาที` (และไม่เกินเพดาน `60 วินาที` เด็ดขาด)
2. **ความถูกต้องของเนื้อหา (`factcheck.json`)**:
   - `overall == "pass"` และ `analogy_check == "ok"`
   - มี `source_url` ที่เปิดอ่านได้จริงแนบอยู่ใน `meta.json`
3. **การติดป้าย AI (`ai_label`)**:
   - `meta.json` ต้องมีข้อความ `"คลิปนี้สร้างด้วยความช่วยเหลือของ AI"` ใน `youtube.description`
   - ตั้งค่า `tiktok.ai_label: true` และ `selfDeclaredMadeWithAi: true` สำหรับ YouTube
4. **ชื่อคลิปและแคปชัน (`meta.json`)**:
   - `youtube.title` ยาวไม่เกิน 60 ตัวอักษร ไม่เป็น Clickbait เกินจริง
   - `tiktok.caption` ยาวไม่เกิน 150 ตัวอักษร พร้อมแฮชแท็ก 3-5 อัน
5. **ลิขสิทธิ์เพลงและภาพ**:
   - เพลงใน `assets/bgm/` เป็นเพลงปลอดลิขสิทธิ์หรือมีใบอนุญาตถูกต้อง
   - ภาพประกอบไม่มีโลโก้แบรนด์ ตัวหนังสือเพี้ยน หรือใบหน้าบุคคลจริง
6. **การอนุมัติ (`status.json`)**:
   - หาก `workflow.require_approval == true` ต้องผ่านการกดปุ่ม `Approve` ใน Telegram (`status == "approved"`) เท่านั้นจึงจะโพสต์ได้
