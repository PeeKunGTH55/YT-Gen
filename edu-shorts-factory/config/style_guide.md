# Style Guide — มาตรฐานงานภาพประจำช่อง

## Style Prefix (ต่อท้ายทุก Image Prompt)
```text
flat vector illustration, soft pastel colors, warm cream and sky blue palette, bold clean outlines, rounded geometric shapes, friendly simple characters, clean minimal background, no text, no letters, no numbers, suitable for all ages
```

## Character Description (ตัวละครหลักประจำช่อง NongSongSai)
```text
a friendly round-faced curious kid character named "Nong SongSai" wearing a bright yellow hoodie, round glasses, navy shorts, short dark hair, expressive eyes, consistent proportions
```

## Reference Image (สำหรับโหมด Image-to-Image / Character Reference)
- พาธไฟล์อ้างอิง: `assets/character_ref.png`
- เมื่อมีไฟล์นี้อยู่ในระบบ ขั้น `05_images.py` จะส่งแนบไปกับโมเดลที่รองรับ Reference Image (เช่น `fal-ai/flux-pro/kontext` หรือ IP-Adapter) เพื่อล็อกหน้าตาและชุดของตัวละครให้ตรงกันทุกฉาก

## Color Palette
- Background Primary: `#FDFBF7` (Warm Cream)
- Background Secondary: `#EAF4F8` (Soft Sky Blue)
- Accent Primary: `#FFB703` (Warm Yellow)
- Accent Secondary: `#FB8500` (Soft Orange)
- Outline / Deep Contrast: `#1D3557` (Deep Navy)

## กฎเหล็กด้านการจัดองค์ประกอบภาพ (Composition Rules)
1. อัตราส่วน `9:16` แนวตั้ง (`1080x1920`)
2. วัตถุหลักและตัวละครอยู่บริเวณกลาง 60% ของเฟรม (`Y: 200px - 1350px`)
3. เว้นพื้นที่ด้านบน 10% และด้านล่าง 25% ให้เป็นพื้นหลังโล่ง เพื่อให้ซับไตเติลและ UI ของแอปไม่บังจุดสำคัญของภาพ
4. ห้ามมีตัวหนังสือ ตัวเลข โลโก้ หรือใบหน้าบุคคลจริงในภาพเด็ดขาด
