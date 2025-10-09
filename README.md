```markdown
# RUN_LOCAL.md — รันท้องถิ่น (quick copy & paste)

1) เตรียมไฟล์
- วางไฟล์ที่ได้: app.py, requirements.txt, Procfile, .env.example, run_local.sh
- คัดลอก .env.example เป็น .env แล้วกรอกค่า environment variables (CHANNEL_ACCESS_TOKEN, CHANNEL_SECRET, FIREBASE_CREDENTIALS_JSON, ADMIN_API_KEY, ADMIN_LINE_ID)

2) เตรียม FIREBASE_CREDENTIALS_JSON (ถ้าใช้ไฟล์ service-account.json)
- ถ้ามี jq:
  export FIREBASE_CREDENTIALS_JSON="$(jq -c . service-account.json)"
- ถ้าไม่มี jq:
  export FIREBASE_CREDENTIALS_JSON="$(python -c 'import json,sys;print(json.dumps(json.load(open(\"service-account.json\"))))')"
- หรือเพิ่มค่า JSON ลงในไฟล์ .env (คัดลอกเป็นบรรทัดเดียว)

3) ติดตั้งและรัน (Linux / macOS)
- ให้สิทธิ์สคริปต์:
  chmod +x run_local.sh
- รัน:
  ./run_local.sh

4) ทดสอบด้วย ngrok (ถ้าต้องการทดสอบ LINE webhook)
- ngrok http 5000
- คัดลอก URL ของ ngrok แล้วตั้ง Webhook URL ใน LINE Developers เป็น:
  https://<NGROK_ID>.ngrok.io/webhook
- เปิด webhook ใน LINE Developers แล้วทดสอบส่งข้อความจาก LINE

5) ตัวอย่าง curl สำหรับ REST API
- สร้าง personnel (ต้องใช้ ADMIN_API_KEY):
  curl -X POST http://localhost:5000/api/personnel \
    -H "Authorization: Bearer <ADMIN_API_KEY>" \
    -H "Content-Type: application/json" \
    -d '{"name":"สมชาย","duty_priority":1,"phone":"0812345678"}'

- ดึง personnel:
  curl http://localhost:5000/api/personnel

- สร้าง leave (ไม่ต้องใช้ admin):
  curl -X POST http://localhost:5000/api/leaves \
    -H "Content-Type: application/json" \
    -d '{"personnel_name":"สมชาย","leave_type":"ลากิจ","start_date":"2025-10-10","end_date":"2025-10-11","reason":"ธุระ"}'

6) ข้อควรระวัง
- FIREBASE_CREDENTIALS_JSON ต้องเป็น JSON ที่ถูกต้อง หากผิด bot จะไม่เชื่อม Firestore
- การเสิร์ฟรูปภาพจาก /tmp อาจไม่คงที่หลัง restart — พิจารณาใช้ Cloud Storage ถ้าต้องการความคงทน
- ใช้ gunicorn ใน production แทน flask dev server
