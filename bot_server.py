# -*- coding: utf-8 -*-

# ========================================================================================
# นี่คือไฟล์ Server สำหรับ LINE Bot จัดตารางเวร (เวอร์ชัน 2)
# เพิ่มความสามารถในการจดจำสถานะการสนทนา (State Management)
# ========================================================================================

from flask import Flask, request, abort

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)

import os

# --- ส่วนตั้งค่า (เหมือนเดิม) ---
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', '8Qa3lq+KjkF68P1W6xAkkuRyoXpz9YyuQI2nOKJRu/ndsvfGLZIft6ltdgYV8vMEbBkz5AWzYoF+CaS7u0OShm uZvo5Yufb6+Xvr4gBti4Gc4cp45MCnyD0cte94vZyyEhLKC3WJKvd9usUXqCwrOgdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '1d0c51790d0bff2b98dbb98dc8f72663')
# -------------------------

app = Flask(__name__)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ========================================================================================
# ส่วนใหม่: หน่วยความจำระยะสั้นของ Bot
# เราจะใช้ตัวแปรนี้เพื่อเก็บว่า User แต่ละคนกำลังคุยอยู่ขั้นตอนไหน
# ========================================================================================
user_states = {}
# ตัวอย่างข้อมูล:
# user_states = {
#     'U12345...': {'step': 'awaiting_leave_type', 'data': {}},
#     'U67890...': {'step': 'awaiting_name', 'data': {'type': 'ลาพัก'}}
# }
# ========================================================================================

@app.route("/webhook", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """
    ฟังก์ชันนี้จะทำงานทุกครั้งที่มีคนส่ง "ข้อความ" เข้ามา
    Logic จะถูกปรับปรุงให้ตรวจสอบ "สถานะการสนทนา" ก่อน
    """
    user_id = event.source.user_id
    user_message = event.message.text

    # --- ส่วนที่ 1: ตรวจสอบว่าผู้ใช้กำลังอยู่ในระหว่างการสนทนาหรือไม่ ---
    if user_id in user_states:
        # (ในอนาคต เราจะมาเขียน Logic การคุยโต้ตอบในส่วนนี้)
        # เช่น ถ้า state คือ 'awaiting_leave_type' ให้ทำอะไรต่อ
        pass # ตอนนี้ปล่อยผ่านไปก่อน

    # --- ส่วนที่ 2: การจัดการคำสั่งเริ่มต้น (เมื่อไม่ได้อยู่ในระหว่างการสนทนา) ---

    # คำสั่ง: เรียกใช้งาน Bot
    if user_message == '#Bot01':
        # (เหมือนเดิม)
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="📝 แจ้งลา/ราชการ", text="#แจ้งลา")),
            QuickReplyButton(action=MessageAction(label="🗓️ จัดเวรประจำวัน", text="#จัดเวร")),
            QuickReplyButton(action=MessageAction(label="📄 ดูข้อมูลการลา", text="#ดูข้อมูลลา"))
        ])
        reply_message = TextSendMessage(
            text="มีอะไรให้รับใช้ครับนายท่าน",
            quick_reply=quick_reply_buttons
        )
        line_bot_api.reply_message(event.reply_token, reply_message)

    # คำสั่งใหม่: เริ่มกระบวนการแจ้งลา
    elif user_message == '#แจ้งลา':
        # 1. บันทึกสถานะของผู้ใช้คนนี้ไว้ใน "หน่วยความจำ"
        user_states[user_id] = {'step': 'awaiting_leave_type', 'data': {}}
        app.logger.info(f"User {user_id} started leave process. Current states: {user_states}")

        # 2. สร้างปุ่มตัวเลือกประเภทการลา
        leave_type_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ลาพัก", text="ลาพัก")),
            QuickReplyButton(action=MessageAction(label="ลากิจ", text="ลากิจ")),
            QuickReplyButton(action=MessageAction(label="ลาป่วย", text="ลาป่วย")),
            QuickReplyButton(action=MessageAction(label="ราชการ", text="ราชการ")),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ])

        # 3. ส่งข้อความถามกลับไปพร้อมปุ่ม
        reply_message = TextSendMessage(
            text="กรุณาเลือกประเภทการลาครับ",
            quick_reply=leave_type_buttons
        )
        line_bot_api.reply_message(event.reply_token, reply_message)
    
    # คำสั่งใหม่: ยกเลิกการดำเนินการ
    elif user_message == '#ยกเลิก':
        if user_id in user_states:
            # ลบสถานะของผู้ใช้ออกจาก "หน่วยความจำ"
            del user_states[user_id]
            app.logger.info(f"User {user_id} cancelled. Current states: {user_states}")
            # ส่งข้อความยืนยัน
            reply_message = TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ")
            line_bot_api.reply_message(event.reply_token, reply_message)


# ส่วนสำหรับรัน Server (ปรับปรุงเล็กน้อยให้รองรับการทำงานบน Render)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

