# -*- coding: utf-8 -*-

# ========================================================================================
# นี่คือไฟล์ Server สำหรับ LINE Bot จัดตารางเวร (เวอร์ชัน 3)
# เพิ่ม Logic การจัดการสถานะสนทนา และการถามชื่อกำลังพล
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

# --- หน่วยความจำระยะสั้นของ Bot (เหมือนเดิม) ---
user_states = {}

# --- ส่วนใหม่: รายชื่อกำลังพลทั้งหมด ---
# ในอนาคตเราจะดึงข้อมูลนี้มาจากฐานข้อมูล แต่ตอนนี้ใส่เป็นรายการไว้ก่อน
personnel_list = [
    "อส.ทพ.บุญธรรม เขียวเข็ม", "อส.ทพ.ชนะศักดิ์ กาสังข์", "อส.ทพ.สนธยา ปราบณรงค์",
    "อส.ทพ.สื่อสาร นะจ๊ะ", "อส.ทพ.กัมพล ทองศรี", "อส.ทพ.อื่นๆ" # เพิ่มชื่ออื่นๆ ตามต้องการ
]
# ------------------------------------

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
    user_id = event.source.user_id
    user_message = event.message.text

    # --- ส่วนที่ 1: ตรวจสอบและจัดการสถานะการสนทนา ---
    if user_id in user_states:
        current_step = user_states[user_id]['step']

        # ขั้นตอนที่ 1: รอรับ "ประเภทการลา"
        if current_step == 'awaiting_leave_type':
            leave_type = user_message
            
            # ตรวจสอบว่าผู้ใช้กดยกเลิกหรือไม่
            if leave_type == '#ยกเลิก':
                del user_states[user_id]
                reply_message = TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ")
                line_bot_api.reply_message(event.reply_token, reply_message)
                return # จบการทำงานสำหรับ user คนนี้

            # 1. บันทึกประเภทการลาที่ผู้ใช้เลือก
            user_states[user_id]['data']['type'] = leave_type
            
            # 2. เปลี่ยนสถานะเป็นรอรับ "ชื่อ"
            user_states[user_id]['step'] = 'awaiting_name'
            app.logger.info(f"User {user_id} selected leave type '{leave_type}'. State: {user_states[user_id]}")

            # 3. สร้างปุ่มรายชื่อกำลังพล
            name_buttons = [QuickReplyButton(action=MessageAction(label=name, text=name)) for name in personnel_list]
            # เพิ่มปุ่มยกเลิก
            name_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
            
            # 4. ถามคำถามต่อไป
            reply_message = TextSendMessage(
                text="กรุณาเลือกกำลังพลที่ต้องการแจ้งลาครับ",
                quick_reply=QuickReply(items=name_buttons)
            )
            line_bot_api.reply_message(event.reply_token, reply_message)
            return # จบการทำงานเพื่อรอคำตอบถัดไป

        # (เราจะมาเพิ่ม Logic สำหรับ step 'awaiting_name' ที่นี่ในครั้งต่อไป)

    # --- ส่วนที่ 2: การจัดการคำสั่งเริ่มต้น ---
    # คำสั่ง: ยกเลิก (กรณีที่อาจจะค้างอยู่)
    if user_message == '#ยกเลิก':
        if user_id in user_states:
            del user_states[user_id]
            reply_message = TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ")
            line_bot_api.reply_message(event.reply_token, reply_message)
        return

    # คำสั่ง: เรียกใช้งาน Bot
    if user_message == '#Bot01':
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

    # คำสั่ง: เริ่มกระบวนการแจ้งลา
    elif user_message == '#แจ้งลา':
        user_states[user_id] = {'step': 'awaiting_leave_type', 'data': {}}
        app.logger.info(f"User {user_id} started leave process. Current states: {user_states}")
        leave_type_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ลาพัก", text="ลาพัก")),
            QuickReplyButton(action=MessageAction(label="ลากิจ", text="ลากิจ")),
            QuickReplyButton(action=MessageAction(label="ลาป่วย", text="ลาป่วย")),
            QuickReplyButton(action=MessageAction(label="ราชการ", text="ราชการ")),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ])
        reply_message = TextSendMessage(
            text="กรุณาเลือกประเภทการลาครับ",
            quick_reply=leave_type_buttons
        )
        line_bot_api.reply_message(event.reply_token, reply_message)


# ส่วนสำหรับรัน Server
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

