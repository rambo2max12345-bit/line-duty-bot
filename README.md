```markdown
# LINE Duty Bot (Render Deployment)

สรุปไฟล์ที่เพิ่ม/แก้ไข:
- app.py (แก้ไขเพื่อใช้งานกับ Firestore/LINE ถูกต้อง, แก้ปัญหา reply_token, postback parsing, status constants)
- requirements.txt
- Procfile
- render.yaml (template สำหรับ Deploy บน Render)
- .env.example
---

การเตรียมใช้งาน (สั้นๆ):
1. สร้าง Firebase service account JSON และเก็บเป็นค่า ENV FIREBASE_CREDENTIALS_JSON (ใส่เป็น JSON string)
2. ตั้งค่า CHANNEL_ACCESS_TOKEN และ CHANNEL_SECRET ของ LINE Messaging API ใน environment variables ของ Render
3. ตั้งค่า ADMIN_LINE_ID เป็น LINE userId ของแอดมิน (หรือหลายคนคั่นด้วย comma)
4. ตรวจสอบว่าฟอนต์ (เช่น Sarabun-Regular.ttf) อยู่ใน repository หรือระบุ FONT_FILENAME ใน ENV
5. Deploy บน Render โดยเชื่อมกับ repo นี้ หรืออัปโหลดโค้ด แล้วใช้ render.yaml หรือตั้งค่า Manual:
   - Build Command: pip install -r requirements.txt
   - Start Command: gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT

ข้อควรระวัง:
- FIREBASE_CREDENTIALS_JSON ควรเป็น JSON ที่ถูกต้อง — หากใส่ผิดจะไม่สามารถเชื่อม Firebase ได้
- LINE webhook ต้องชี้ไปที่ /webhook ของแอป (HTTPS)
- การเสิร์ฟรูปภาพจาก /tmp อาจไม่คงที่ระหว่าง instance restart — หากต้องการเก็บรูประยะยาวให้ใช้ Cloud Storage แทน
- ข้อความใน TextSendMessage ของ LINE เป็นข้อความธรรมดา (ไม่รองรับ Markdown) หากต้องการฟอร์แมตให้พิจารณาใช้ Flex Messages

ถ้าต้องการ ผมสามารถ:
- เปิด PR ใน repo ของคุณ (ต้องการ repo URL + 권한)
- ปรับให้รองรับ multipart admin list ใน UI
- ย้ายการเก็บรูปไปที่ Google Cloud Storage และส่ง URL ที่เสถียรกว่า
