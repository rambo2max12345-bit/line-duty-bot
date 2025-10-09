# -*- coding: utf-8 -*-

from flask import Flask, request, abort, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    DatetimePickerAction, PostbackEvent,
    ImageSendMessage
)
import os
import json
from datetime import datetime, timedelta
import uuid

import firebase_admin
from firebase_admin import credentials, firestore

from dotenv import load_dotenv
load_dotenv()  # สำหรับรันทดสอบบนเครื่องตัวเอง (Local)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

# --- ตั้งค่า LINE (แก้ไขแล้ว) ---
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")

app = Flask(__name__)

# ตรวจสอบว่ามี Token หรือไม่ก่อนสร้าง instance
if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    app.logger.error("CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET must be set as environment variables.")
    # ใน Production อาจจะ exit หรือจัดการ error อื่นๆ
    line_bot_api = None
    handler = None
else:
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(CHANNEL_SECRET)

# --- เชื่อม Firebase ---
try:
    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if firebase_json:
        cred_dict = json.loads(firebase_json)
        cred = credentials.Certificate(cred_dict)
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
        app.logger.info("Firebase connected successfully.")
    else:
        db = None
        app.logger.warning("FIREBASE_CREDENTIALS_JSON not found. Firebase not connected.")
except Exception as e:
    db = None
    app.logger.error(f"Firebase connection failed: {e}")

# --- หน่วยความจำและรายชื่อ ---
user_states = {}
personnel_list = [
    "อส.ทพ.บุญธรรม เขียวเข็ม", "อส.ทพ.สนธยา ปราบณรงค์", "อส.ทพ.คเนศ เกียรติขวัญบุตร",
    "อส.ทพ.ณัฐพล แสวงทรัพย์", "อส.ทพ.อาวุธ มณี", "อส.ทพ.อนุชา คำลาด",
    "อส.ทพ.วีระยุทธ บุญมานัส", "อส.ทพ.กล้าณรงค์ คงลำธาร", "อส.ทพ.ชนะศักดิ์ กาสังข์",
    "อส.ทพ.เอกชัย ขนาดผล", "อส.ทพ.อนุชา นพวงศ์", "อส.ทพ.โกวิทย์ ทองขาวบัว",
    "อส.ทพ.สื่อสาร นะครับ", "อส.ทพ.กัมพล ทองศรี"
]

# --- Serve Image ---
@app.route("/images/<filename>")
def serve_image(filename):
    image_dir = '/tmp/line_bot_images'
    # สร้าง directory ถ้ายังไม่มี
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)
    return send_from_directory(image_dir, filename)

# --- Webhook ---
@app.route("/webhook", methods=['POST'])
def callback():
    if not handler:
        abort(500) # Server is misconfigured
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- Message Event Handler ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not line_bot_api:
        return # ไม่ทำงานถ้า line_bot_api ไม่ถูกสร้าง
        
    user_id = event.source.user_id
    user_message = event.message.text

    # --- จัดการ State ---
    if user_id in user_states:
        current_step = user_states[user_id]['step']
        if current_step.startswith("awaiting"):
            pass
    else:
        # --- คำสั่ง Rich Menu ---
        if user_message == "#แจ้งลา":
            user_states[user_id] = {"step": "awaiting_leave_type", "data": {}}
            leave_buttons = [
                QuickReplyButton(action=MessageAction(label="ลาพัก", text="ลาพัก")),
                QuickReplyButton(action=MessageAction(label="ลากิจ", text="ลากิจ")),
                QuickReplyButton(action=MessageAction(label="ลาป่วย", text="ลาป่วย")),
                QuickReplyButton(action=MessageAction(label="ราชการ", text="ราชการ")),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ]
            reply_msg = TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=QuickReply(items=leave_buttons))
            line_bot_api.reply_message(event.reply_token, reply_msg)
        elif user_message == "#รีเซ็ต":
            if user_id in user_states: del user_states[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔄️ รีเซ็ตเรียบร้อยแล้วครับ"))

# --- Postback Event Handler ---
@handler.add(PostbackEvent)
def handle_postback(event):
    pass

# --- Run Server ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
