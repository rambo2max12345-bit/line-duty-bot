# -*- coding: utf-8 -*-

# ========================================================================================
# นี่คือไฟล์ Server สำหรับ LINE Bot จัดตารางเวร (เวอร์ชัน 6 - สมบูรณ์)
# เพิ่มความสามารถในการรับวันสิ้นสุด, สรุปข้อมูล, และสิ้นสุดกระบวนการ
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

# --- ส่วนตั้งค่า (เหมือนเดิม) ---
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', '8Qa3lq+KjkF68P1W6xAkkuRyoXpz9YyuQI2nOKJRu/ndsvfGLZIft6ltdgYV8vMEbBkz5AWzYoF+CaS7u0OShm uZvo5Yufb6+Xvr4gBti4Gc4cp45MCnyD0cte94vZyyEhLKC3WJKvd9usUXqCwrOgdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '1d0c51790d0bff2b98dbb98dc8f72663')
# -------------------------

app = Flask(__name__)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- หน่วยความจำระยะสั้นของ Bot (เหมือนเดิม) ---
user_states = {}

# --- รายชื่อกำลังพลทั้งหมด (เหมือนเดิม) ---
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


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # ฟังก์ชันนี้จะจัดการกับ "ข้อความตัวอักษร" เท่านั้น
    user_id = event.source.user_id
    user_message = event.message.text

    if user_id in user_states:
        current_step = user_states[user_id]['step']
        # ... (โค้ดส่วนนี้เหมือนเดิมทั้งหมด) ...
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

    # --- ส่วนจัดการคำสั่งเริ่มต้น (เหมือนเดิม) ---
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


@handler.add(PostbackEvent)
def handle_postback(event):
    # ฟังก์ชันนี้จะจัดการกับสัญญาณจากปฏิทิน
    user_id = event.source.user_id
    postback_data = event.postback.data

    if user_id in user_states:
        current_step = user_states[user_id]['step']

        if current_step == 'awaiting_start_date' and postback_data == 'action=select_start_date':
            # ... (ส่วนนี้ทำงานเหมือนเดิม) ...
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
        
        # ==============================================================================
        # ส่วนที่เพิ่มเข้ามาใหม่: รอรับ "วันสิ้นสุด"
        # ==============================================================================
        elif current_step == 'awaiting_end_date' and postback_data == 'action=select_end_date':
            selected_end_date = event.postback.params['date']
            
            # 1. บันทึกวันสิ้นสุด
            user_states[user_id]['data']['end_date'] = selected_end_date
            app.logger.info(f"User {user_id} selected end date '{selected_end_date}'. Final data: {user_states[user_id]['data']}")
            
            # 2. ดึงข้อมูลทั้งหมดที่เก็บมา
            final_data = user_states[user_id]['data']
            
            # 3. สร้างข้อความสรุป
            # (แปลง YYYY-MM-DD เป็น DD/MM/YYYY)
            start_date_formatted = datetime.strptime(final_data['start_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
            end_date_formatted = datetime.strptime(final_data['end_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
            
            summary_message = (
                "✅ **บันทึกข้อมูลเรียบร้อย**\n\n"
                f"**ประเภท:** {final_data['type']}\n"
                f"**ชื่อ:** {final_data['name']}\n"
                f"**ตั้งแต่:** {start_date_formatted}\n"
                f"**ถึง:** {end_date_formatted}"
            )
            
            # 4. ส่งข้อความสรุปกลับไป
            # (ในอนาคต เราจะเพิ่มโค้ดบันทึกลง Firebase ก่อนส่งข้อความนี้)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=summary_message))
            
            # 5. ล้างสถานะของผู้ใช้คนนี้ออกจากหน่วยความจำ เป็นการจบกระบวนการ
            del user_states[user_id]
            return
        # ==============================================================================

# ส่วนสำหรับรัน Server
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

