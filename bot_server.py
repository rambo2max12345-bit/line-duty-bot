# -*- coding: utf-8 -*-

# ========================================================================================
# นี่คือไฟล์ Server สำหรับ LINE Bot จัดตารางเวร (เวอร์ชัน 9 - ชุดใหญ่ไฟกระพริบ!)
# เพิ่มความสามารถในการ "จัดเวรประจำวัน"
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
from datetime import datetime, timedelta # <-- เพิ่ม timedelta สำหรับคำนวณเวลา
import json
import firebase_admin
from firebase_admin import credentials, firestore

# --- ส่วนตั้งค่า LINE ---
CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', '8Qa3lq+KjkF68P1W6xAkkuRyoXpz9YyuQI2nOKJRu/ndsvfGLZIft6ltdgYV8vMEbBkz5AWzYoF+CaS7u0OShm uZvo5Yufb6+Xvr4gBti4Gc4cp45MCnyD0cte94vZyyEhLKC3WJKvd9usUXqCwrOgdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '1d0c51790d0bff2b98dbb98dc8f72663')
# -------------------------

app = Flask(__name__)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# --- ส่วนเชื่อมต่อ Firebase ---
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

# --- หน่วยความจำและรายชื่อ ---
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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    # --- ส่วนจัดการ State การสนทนา ---
    if user_id in user_states:
        current_step = user_states[user_id]['step']

        # --- State การแจ้งลา (เหมือนเดิม) ---
        if current_step == 'awaiting_leave_type':
            # ... (โค้ดส่วนนี้เหมือนเดิม)
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
            # ... (โค้ดส่วนนี้เหมือนเดิม)
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
        
        # ==============================================================================
        # ส่วนที่เพิ่มเข้ามาใหม่: จัดการ State การจัดเวร
        # ==============================================================================
        elif current_step == 'awaiting_sergeant':
            sergeant_name = user_message
            if sergeant_name == '#ยกเลิก':
                del user_states[user_id]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกการจัดเวรเรียบร้อยแล้วครับ"))
                return
            
            # --- เริ่มกระบวนการคำนวณตารางเวร ---
            try:
                # 1. ดึงข้อมูลคนลาจาก Firebase (เหมือนฟังก์ชัน #ดูข้อมูลลา)
                today_str = datetime.now().strftime('%Y-%m-%d')
                docs_query = db.collection('leave_requests').where('start_date', '<=', today_str).stream()
                on_leave_names = []
                for doc in docs_query:
                    leave_data = doc.to_dict()
                    if leave_data.get('end_date', '1970-01-01') >= today_str:
                        on_leave_names.append(leave_data['name'])
                
                # 2. คัดกรองกำลังพลที่พร้อมปฏิบัติหน้าที่
                available_personnel = [p for p in personnel_list if p not in on_leave_names]
                
                # 3. ตรวจสอบว่าสิบเวรที่เลือกมานั้นว่างหรือไม่
                if sergeant_name not in available_personnel:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f"⚠️ ขออภัยครับ {sergeant_name} ติดภารกิจ (ลา/ราชการ) ไม่สามารถเป็นสิบเวรได้ กรุณาลองใหม่อีกครั้ง")
                    )
                    del user_states[user_id]
                    return

                # 4. เตรียมรายชื่อสำหรับจัดผลัด (ไม่รวมสิบเวร)
                duty_personnel = [p for p in available_personnel if p != sergeant_name]
                
                if not duty_personnel:
                    reply_text = f"🗓️ **ตารางเวรประจำวันที่ {datetime.now().strftime('%d/%m/%Y')}**\n\n"
                    reply_text += f"**สิบเวร:** {sergeant_name}\n\n"
                    reply_text += "⚠️ ไม่มีกำลังพลเหลือสำหรับจัดผลัดเวร"
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
                    del user_states[user_id]
                    return

                # 5. คำนวณเวลาเข้าเวร
                start_time = datetime.strptime("18:00", "%H:%M")
                total_minutes = 12 * 60 # 12 ชั่วโมง
                minutes_per_person = total_minutes / len(duty_personnel)
                
                schedule = []
                current_time = start_time
                for person in duty_personnel:
                    end_time = current_time + timedelta(minutes=minutes_per_person)
                    # จัดการกรณีข้ามวันเที่ยงคืน
                    end_display_time = end_time
                    if end_time.day > start_time.day:
                        end_display_time = datetime.strptime(end_time.strftime('%H:%M'), '%H:%M')
                    
                    time_slot = f"{current_time.strftime('%H:%M')} - {end_display_time.strftime('%H:%M')}"
                    schedule.append({'name': person, 'time': time_slot})
                    current_time = end_time

                # 6. สร้างข้อความตารางเวร
                today_formatted = datetime.now().strftime('%d/%m/%Y')
                reply_text = f"🗓️ **ตารางเวรประจำวันที่ {today_formatted}**\n\n"
                reply_text += f"**สิบเวร:** {sergeant_name}\n\n"
                reply_text += "**ผลัดเวร:**\n"
                for i, entry in enumerate(schedule, 1):
                    reply_text += f"{i}. {entry['time']}: {entry['name']}\n"
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text.strip()))
            
            except Exception as e:
                app.logger.error(f"Error during scheduling: {e}")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดระหว่างการคำนวณตารางเวร"))
            
            finally:
                # 7. ล้าง state ไม่ว่าจะสำเร็จหรือล้มเหลว
                if user_id in user_states:
                    del user_states[user_id]
            return
        # ==============================================================================


    # --- ส่วนจัดการคำสั่งหลัก ---
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

    elif user_message == '#ดูข้อมูลลา':
        # ... (โค้ดส่วนนี้เหมือนเดิม)
        if not db:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="⚠️ ขออภัยครับ ไม่สามารถเชื่อมต่อกับฐานข้อมูลได้ในขณะนี้")
            )
            return

        try:
            today_str = datetime.now().strftime('%Y-%m-%d')
            docs_query = db.collection('leave_requests').where('start_date', '<=', today_str).stream()
            on_leave_today = []
            for doc in docs_query:
                leave_data = doc.to_dict()
                if leave_data.get('end_date', '1970-01-01') >= today_str:
                    on_leave_today.append(leave_data)
            
            if not on_leave_today:
                reply_text = "✅ ไม่มีกำลังพลลา/ราชการในวันนี้ครับ"
            else:
                reply_text = "📄 **สรุปกำลังพลลา/ราชการ วันนี้**\n\n"
                for leave in on_leave_today:
                    start_date_formatted = datetime.strptime(leave['start_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                    end_date_formatted = datetime.strptime(leave['end_date'], '%Y-%m-%d').strftime('%d/%m/%Y')
                    reply_text += (
                        f"**ชื่อ:** {leave['name']}\n"
                        f"**ประเภท:** {leave['leave_type']}\n"
                        f"**ช่วงเวลา:** {start_date_formatted} - {end_date_formatted}\n\n"
                    )
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text.strip()))

        except Exception as e:
            app.logger.error(f"Error fetching from Firestore: {e}")
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการดึงข้อมูลการลา")
            )
        return

    # ==============================================================================
    # ส่วนที่เพิ่มเข้ามาใหม่: จัดการคำสั่ง "#จัดเวร"
    # ==============================================================================
    elif user_message == '#จัดเวร':
        user_states[user_id] = {'step': 'awaiting_sergeant'}
        sergeant_buttons = [QuickReplyButton(action=MessageAction(label=name, text=name)) for name in personnel_list]
        sergeant_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
        reply_message = TextSendMessage(
            text="กรุณาเลือกกำลังพลที่จะทำหน้าที่ 'สิบเวร' ครับ",
            quick_reply=QuickReply(items=sergeant_buttons)
        )
        line_bot_api.reply_message(event.reply_token, reply_message)
        return
    # ==============================================================================


@handler.add(PostbackEvent)
def handle_postback(event):
    # --- ส่วนนี้เหมือนเดิมทั้งหมด ---
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
    app.run(host='0.0.0' , port=port)

