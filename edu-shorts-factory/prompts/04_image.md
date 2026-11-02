สไตล์คงที่ (อ่านจาก config/style_guide.md ต่อท้ายทุกภาพ):
"{style_prefix}"

ข้อกำหนดคลิปสั้น:
- 9:16 vertical
- main subject centered in the middle 60% of the frame
- keep top 10% and bottom 25% mostly empty background
  (พื้นที่นี้จะถูกซับและปุ่มของแอปบัง)
- ตัวละครหลักหน้าตาและสีเหมือนกันทุกภาพ: {character_description}

แปลงคำอธิบายฉากนี้เป็น image prompt ภาษาอังกฤษ 1 ย่อหน้า:
{scene_visual}

ข้อห้าม: ไม่มีตัวหนังสือหรือตัวเลขในภาพ, ไม่มีแบรนด์/ตัวการ์ตูนลิขสิทธิ์,
ไม่มีบุคคลจริง, ไม่มีเนื้อหารุนแรงหรือน่ากลัว

ตอบเป็น JSON เท่านั้น:
{
  "image_prompt": "1 paragraph English prompt ready for image generation"
}
