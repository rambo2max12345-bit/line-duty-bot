# -*- coding: utf-8 -*-

# ========================================================================================
# นี่คือไฟล์ Server สำหรับ LINE Bot จัดตารางเวร (เวอร์ชัน 7.1 - แก้ไขข้อผิดพลาด)
# ย้ายลำดับการเชื่อมต่อ Firebase เพื่อแก้ไข NameError
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
    QuickReply, QuickReplyButton, MessageAction,
    DatetimePickerAction,
    PostbackEvent
)

import os
from datetime import datetime
import json
import firebase_admin
from firebase_admin import credentials, firestore

# --- ส่วนตั้งค่า LINE ---
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', '8Qa3lq+KjkF68P1W6xAkkuRyoXpz9YyuQI2nOKJRu/ndsvfGLZIft6ltdgYV8vMEbBkz5AWzYoF+CaS7u0OShm uZvo5Yufb6+Xvr4gBti4Gc4cp45MCnyD0cte94vZyyEhLKC3WJKvd9usUXqCwrOgdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '1d0c51790d0bff2b98dbb98dc8f72663')
# -------------------------

app = Flask(__name__) # <-- สร้าง app ขึ้นมาก่อน
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- ย้ายส่วน import และเชื่อมต่อ Firebase มาไว้ตรงนี้ ---
try:
    firebase_credentials_json_str = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if firebase_credentials_json_str:
        firebase_credentials_json = json.loads(firebase_credentials_json_str)
        cred = credentials.Certificate(firebase_credentials_json)
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
# -----------------------------------

# --- หน่วยความจำและรายชื่อ (เหมือนเดิม) ---
user_states = {}
personnel_list = [
    "อส.ทพ.บุญธรรม เขียวเข็ม", "อส.ทพ.ชนะศักดิ์ กาสังข์", "อส.ทพ.สนธยา ปราบณรงค์",
    "อส.ทพ.สื่อสาร นะจ๊ะ", "อส.ทพ.กัมพล ทองศรี", "อส.ทพ.อื่นๆ"
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

# --- ส่วนจัดการข้อความ (handle_message) - เหมือนเดิม ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text
    if user_id in user_states:
        current_step = user_states[user_id]['step']
        if current_step == 'awaiting_leave_type':
            leave_type = user_message
            if leave_type == '#ยกเลิก':
                del user_states[user_id]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ"))
                return
            user_states[user_id]['data']['type'] = leave_type
            user_states[user_id]['step'] = 'awaiting_name'
            name_buttons = [QuickReplyButton(action=MessageAction(label=name, text=name)) for name in personnel_list]
            name_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
            reply_message = TextSendMessage(text="กรุณาเลือกกำลังพลที่ต้องการแจ้งลาครับ", quick_reply=QuickReply(items=name_buttons))
            line_bot_api.reply_message(event.reply_token, reply_message)
            return

        elif current_step == 'awaiting_name':
            selected_name = user_message
            if selected_name == '#ยกเลิก':
                del user_states[user_id]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ"))
                return
            user_states[user_id]['data']['name'] = selected_name
            user_states[user_id]['step'] = 'awaiting_start_date'
            today = datetime.now().strftime('%Y-%m-%d')
            date_picker_start = QuickReply(items=[
                QuickReplyButton(action=DatetimePickerAction(label="เลือกวันเริ่มต้น", data="action=select_start_date", mode="date", initial=today, min=today)),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ])
            reply_message = TextSendMessage(text="กรุณาเลือกวันที่เริ่มต้นลาครับ", quick_reply=date_picker_start)
            line_bot_api.reply_message(event.reply_token, reply_message)
            return

    if user_message == '#ยกเลิก':
        if user_id in user_states:
            del user_states[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ"))
        return
    if user_message == '#Bot01':
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="📝 แจ้งลา/ราชการ", text="#แจ้งลา")),
            QuickReplyButton(action=MessageAction(label="🗓️ จัดเวรประจำวัน", text="#จัดเวร")),
            QuickReplyButton(action=MessageAction(label="📄 ดูข้อมูลการลา", text="#ดูข้อมูลลา"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="มีอะไรให้รับใช้ครับนายท่าน", quick_reply=quick_reply_buttons))
    elif user_message == '#แจ้งลา':
        user_states[user_id] = {'step': 'awaiting_leave_type', 'data': {}}
        leave_type_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="ลาพัก", text="ลาพัก")),
            QuickReplyButton(action=MessageAction(label="ลากิจ", text="ลากิจ")),
            QuickReplyButton(action=MessageAction(label="ลาป่วย", text="ลาป่วย")),
            QuickReplyButton(action=MessageAction(label="ราชการ", text="ราชการ")),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=leave_type_buttons))
# ----------------------------------------------


@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    postback_data = event.postback.data

    if user_id in user_states:
        current_step = user_states[user_id]['step']

        if current_step == 'awaiting_start_date' and postback_data == 'action=select_start_date':
            selected_date = event.postback.params['date']
            user_states[user_id]['data']['start_date'] = selected_date
            user_states[user_id]['step'] = 'awaiting_end_date'
            date_picker_end = QuickReply(items=[
                QuickReplyButton(action=DatetimePickerAction(label="เลือกวันสิ้นสุด", data="action=select_end_date", mode="date", initial=selected_date, min=selected_date)),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ])
            reply_message = TextSendMessage(text="กรุณาเลือกวันสิ้นสุดการลาครับ", quick_reply=date_picker_end)
            line_bot_api.reply_message(event.reply_token, reply_message)
            return
        
        elif current_step == 'awaiting_end_date' and postback_data == 'action=select_end_date':
            selected_end_date = event.postback.params['date']
            user_states[user_id]['data']['end_date'] = selected_end_date
            
            final_data = user_states[user_id]['data']
            
            if db:
                try:
                    doc_ref = db.collection('leave_requests').document()
                    doc_ref.set({
                        'leave_type': final_data['type'],
                        'name': final_data['name'],
                        'start_date': final_data['start_date'],
                        'end_date': final_data['end_date'],
                        'status': 'pending',
                        'timestamp': firestore.SERVER_TIMESTAMP
                    })
                    app.logger.info(f"Successfully saved data to Firestore for {final_data['name']}")
                    summary_message_text = "✅ **บันทึกข้อมูลลงระบบเรียบร้อย**\n\n"
                except Exception as e:
                    app.logger.error(f"Error saving to Firestore: {e}")
                    summary_message_text = "⚠️ **เกิดข้อผิดพลาดในการบันทึก**\n\n"
            else:
                summary_message_text = "ℹ️ **แสดงข้อมูลสรุป (ยังไม่บันทึก)**\n\n"
            
            start_date_formatted = datetime.strptime(final_data['start_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
            end_date_formatted = datetime.strptime(final_data['end_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
            
            summary_message_text += (
                f"**ประเภท:** {final_data['type']}\n"
                f"**ชื่อ:** {final_data['name']}\n"
                f"**ตั้งแต่:** {start_date_formatted}\n"
                f"**ถึง:** {end_date_formatted}"
            )
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=summary_message_text))
            
            del user_states[user_id]
            return

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

