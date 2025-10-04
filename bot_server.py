# -*- coding: utf-8 -*-

# ========================================================================================
# นี่คือไฟล์ Server สำหรับ LINE Bot จัดตารางเวร (เวอร์ชัน 13 - Final Rich Menu)
# ========================================================================================

from flask import Flask, request, abort, send_from_directory
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
    PostbackEvent,
    ImageSendMessage
)

import os
from datetime import datetime, timedelta
import json
import firebase_admin
from firebase_admin import credentials, firestore
import uuid

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

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
    "อส.ทพ.บุญธรรม เขียวเข็ม", "อส.ทพ.สนธยา ปราบณรงค์", "เกียรติขวัญบุตร อส.ทพ.คเนศ",
    "อส.ทพ.ณัฐพล แสวงทรัพย์", "อส.ทพ.อาวุธ มณี", "อส.ทพ.อนุชา คำลาด",
    "อส.ทพ.วีระยุทธ บุญมานัส", "อส.ทพ.กล้าณรงค์ คงลำธาร", "อส.ทพ.ชนะศักดิ์ กาสังข์",
    "อส.ทพ.เอกชัย ขนาดผล", "อส.ทพ.อนุชา นพวงศ์", "อส.ทพ.โกวิทย์ ทองขาวบัว",
    "อส.ทพ.สื่อสาร นะครับ", "อส.ทพ.กัมพล ทองศรี"
]
# ------------------------------------

@app.route("/images/<filename>")
def serve_image(filename):
    image_dir = '/tmp/line_bot_images'
    return send_from_directory(image_dir, filename)

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

    if user_id in user_states:
        current_step = user_states[user_id]['step']
        # --- ส่วนจัดการ State การแจ้งลา ---
        if current_step == 'awaiting_leave_type':
            leave_type = user_message
            if leave_type == '#ยกเลิก':
                del user_states[user_id]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกรายการเรียบร้อยแล้วครับ"))
                return
            user_states[user_id]['data']['type'] = leave_type
            user_states[user_id]['step'] = 'awaiting_name'
            name_buttons = [QuickReplyButton(action=MessageAction(label=name[:20], text=name)) for name in personnel_list]
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
        # --- ส่วนจัดการ State การจัดเวร ---
        elif current_step == 'awaiting_sergeant':
            sergeant_name = user_message
            if sergeant_name == '#ยกเลิก':
                del user_states[user_id]
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ยกเลิกการจัดเวรเรียบร้อยแล้วครับ"))
                return
            try:
                today_str = datetime.now().strftime('%Y-%m-%d')
                docs_query = db.collection('leave_requests').where('start_date', '<=', today_str).stream()
                on_leave_names = [doc.to_dict()['name'] for doc in docs_query if doc.to_dict().get('end_date', '1970-01-01') >= today_str]
                available_personnel = [p for p in personnel_list if p not in on_leave_names]
                today_weekday = datetime.now().weekday()
                barber_name = "อส.ทพ.โกวิทย์ ทองขาวบัว"
                barber_duty_days = [1, 3, 5]
                barber_excluded = False
                if today_weekday in barber_duty_days and barber_name in available_personnel:
                    available_personnel.remove(barber_name)
                    barber_excluded = True
                
                if sergeant_name not in available_personnel:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"⚠️ ขออภัยครับ {sergeant_name} ติดภารกิจ"))
                    del user_states[user_id]
                    return
                duty_personnel_ordered = [sergeant_name]
                start_index = personnel_list.index(sergeant_name) + 1
                rotated_master_list = personnel_list[start_index:] + personnel_list[:start_index]
                for person in rotated_master_list:
                    if person in available_personnel and person != sergeant_name:
                        duty_personnel_ordered.append(person)
                
                if not Image: raise ImportError("Pillow library is not installed.")
                width, height = 800, 1000
                bg_color, font_color, header_color = (240, 240, 240), (50, 50, 50), (0, 0, 0)
                font_path = "Sarabun-Regular.ttf"

                try:
                    header_font, body_font, small_font = ImageFont.truetype(font_path, 40), ImageFont.truetype(font_path, 28), ImageFont.truetype(font_path, 20)
                except IOError:
                    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️เกิดข้อผิดพลาด: ไม่พบไฟล์ฟอนต์ Sarabun-Regular.ttf"))
                    del user_states[user_id]
                    return

                image = Image.new('RGB', (width, height), bg_color)
                draw = ImageDraw.Draw(image)
                today_thai = datetime.now().strftime('%d/%m/%Y')
                draw.text((40, 30), f"ตารางเวรประจำวันที่ {today_thai}", font=header_font, fill=header_color)
                draw.line([(40, 90), (width - 40, 90)], fill=(200, 200, 200), width=2)
                y_pos = 110
                if not duty_personnel_ordered:
                    draw.text((40, y_pos), "ไม่มีกำลังพลสำหรับจัดเวร", font=body_font, fill=(255, 0, 0))
                else:
                    start_time = datetime.strptime("18:00", "%H:%M")
                    minutes_per_person = (12 * 60) / len(duty_personnel_ordered)
                    current_time = start_time
                    draw.text((40, y_pos), "ผลัดเวร:", font=body_font, fill=font_color)
                    y_pos += 50
                    for i, person in enumerate(duty_personnel_ordered, 1):
                        end_time = current_time + timedelta(minutes=minutes_per_person)
                        time_slot = f"{current_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
                        draw.text((60, y_pos), f"{i}. {time_slot}:  {person}", font=body_font, fill=font_color)
                        y_pos += 45
                        current_time = end_time
                if barber_excluded:
                    draw.text((40, y_pos + 20), f"*หมายเหตุ: {barber_name} งดเข้าเวร (ช่างตัดผม)", font=small_font, fill=font_color)

                temp_dir = '/tmp/line_bot_images'
                os.makedirs(temp_dir, exist_ok=True)
                unique_filename = f"{uuid.uuid4()}.png"
                image_path = os.path.join(temp_dir, unique_filename)
                image.save(image_path)
                base_url = request.host_url.replace('http://', 'https://')
                image_url = f"{base_url}images/{unique_filename}"
                line_bot_api.reply_message(event.reply_token, ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
            except Exception as e:
                app.logger.error(f"Error during image roster generation: {e}")
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดระหว่างสร้างภาพตารางเวร"))
            finally:
                if user_id in user_states: del user_states[user_id]
            return
    
    # --- ส่วนจัดการคำสั่งจาก Rich Menu ---
    if user_message == '#แจ้งลา':
        user_states[user_id] = {'step': 'awaiting_leave_type', 'data': {}}
        leave_type_buttons = QuickReply(items=[QuickReplyButton(action=MessageAction(label="ลาพัก",text="ลาพัก")),QuickReplyButton(action=MessageAction(label="ลากิจ",text="ลากิจ")),QuickReplyButton(action=MessageAction(label="ลาป่วย",text="ลาป่วย")),QuickReplyButton(action=MessageAction(label="ราชการ",text="ราชการ")),QuickReplyButton(action=MessageAction(label="❌ ยกเลิก",text="#ยกเลิก"))])
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=leave_type_buttons))
    
    elif user_message == '#จัดเวร':
        user_states[user_id] = {'step': 'awaiting_sergeant'}
        sergeant_buttons = [QuickReplyButton(action=MessageAction(label=name[:20], text=name)) for name in personnel_list]
        sergeant_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
        reply_message = TextSendMessage(text="กรุณาเลือกกำลังพลที่จะทำหน้าที่ 'สิบเวรโรงรถ' (ผลัดที่ 1) ครับ", quick_reply=QuickReply(items=sergeant_buttons))
        line_bot_api.reply_message(event.reply_token, reply_message)
    
    elif user_message == '#ดูข้อมูลลาวันนี้':
        if not db: 
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text="⚠️ ไม่สามารถเชื่อมต่อฐานข้อมูลได้"))
            return
        try:
            today_str=datetime.now().strftime('%Y-%m-%d')
            docs_query=db.collection('leave_requests').where('start_date','<=',today_str).stream()
            on_leave_today=[doc.to_dict() for doc in docs_query if doc.to_dict().get('end_date','1970-01-01')>=today_str]
            if not on_leave_today: 
                reply_text="✅ ไม่มีกำลังพลลา/ราชการในวันนี้ครับ"
            else:
                reply_text="📄 **สรุปกำลังพลลา/ราชการ วันนี้**\n\n"
                for leave in on_leave_today:
                    start_date_formatted=datetime.strptime(leave['start_date'],'%Y-%m-%d').strftime('%d/%m/%Y')
                    end_date_formatted=datetime.strptime(leave['end_date'],'%Y-%m-%d').strftime('%d/%m/%Y')
                    reply_text+=f"**ชื่อ:** {leave['name']}\n**ประเภท:** {leave['leave_type']}\n**ช่วงเวลา:** {start_date_formatted} - {end_date_formatted}\n\n"
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text=reply_text.strip()))
        except Exception as e:
            app.logger.error(f"Error fetching from Firestore: {e}")
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการดึงข้อมูล"))

    elif user_message == '#ดูข้อมูลลาทั้งหมด':
        if not db: 
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text="⚠️ ไม่สามารถเชื่อมต่อฐานข้อมูลได้"))
            return
        try:
            docs = db.collection('leave_requests').order_by('start_date', direction=firestore.Query.DESCENDING).limit(20).stream()
            all_leaves = [doc.to_dict() for doc in docs]
            if not all_leaves: 
                reply_text="ℹ️ ยังไม่มีข้อมูลการลาในระบบครับ"
            else:
                reply_text="📑 **ข้อมูลการลาทั้งหมด (20 รายการล่าสุด)**\n\n"
                for leave in all_leaves:
                    start_date_formatted=datetime.strptime(leave['start_date'],'%Y-%m-%d').strftime('%d/%m/%Y')
                    end_date_formatted=datetime.strptime(leave['end_date'],'%Y-%m-%d').strftime('%d/%m/%Y')
                    reply_text+=f"• {leave['name']} ({leave['leave_type']})\n  {start_date_formatted} - {end_date_formatted}\n\n"
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text=reply_text.strip()))
        except Exception as e:
            app.logger.error(f"Error fetching all leaves: {e}")
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการดึงข้อมูลทั้งหมด"))

    elif user_message == '#รีเซ็ต':
        if user_id in user_states:
            del user_states[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔄️ รีเซ็ตการทำงานเรียบร้อยแล้วครับ"))

    elif user_message == '#สรุปเวรอยู่ระหว่างพัฒนา':
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🛠️ ขออภัยครับ ฟังก์ชัน 'สร้างสรุปเวร' กำลังอยู่ระหว่างการพัฒนาครับ"))

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id=event.source.user_id
    if user_id in user_states:
        current_step=user_states[user_id]['step']
        if current_step=='awaiting_start_date' and event.postback.data=='action=select_start_date':
            selected_date=event.postback.params['date']
            user_states[user_id]['data']['start_date']=selected_date
            user_states[user_id]['step']='awaiting_end_date'
            date_picker_end=QuickReply(items=[QuickReplyButton(action=DatetimePickerAction(label="เลือกวันสิ้นสุด",data="action=select_end_date",mode="date",initial=selected_date,min=selected_date)),QuickReplyButton(action=MessageAction(label="❌ ยกเลิก",text="#ยกเลิก"))])
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text="กรุณาเลือกวันสิ้นสุดการลาครับ",quick_reply=date_picker_end))
            return
        elif current_step=='awaiting_end_date' and event.postback.data=='action=select_end_date':
            selected_end_date=event.postback.params['date']
            user_states[user_id]['data']['end_date']=selected_end_date
            final_data=user_states[user_id]['data']
            if db:
                try:
                    doc_ref=db.collection('leave_requests').document()
                    doc_ref.set({'leave_type':final_data['type'],'name':final_data['name'],'start_date':final_data['start_date'],'end_date':final_data['end_date'],'status':'pending','timestamp':firestore.SERVER_TIMESTAMP})
                    summary_message_text="✅ **บันทึกข้อมูลลงระบบเรียบร้อย**\n\n"
                except Exception as e:
                    app.logger.error(f"Error saving to Firestore: {e}")
                    summary_message_text="⚠️ **เกิดข้อผิดพลาดในการบันทึก**\n\n"
            else:
                summary_message_text="ℹ️ **แสดงข้อมูลสรุป (ยังไม่บันทึก)**\n\n"
            start_date_formatted=datetime.strptime(final_data['start_date'],'%Y-%m-%d').strftime('%d/%m/%Y')
            end_date_formatted=datetime.strptime(final_data['end_date'],'%Y-%m-%d').strftime('%d/%m/%Y')
            summary_message_text+=f"**ประเภท:** {final_data['type']}\n**ชื่อ:** {final_data['name']}\n**ตั้งแต่:** {start_date_formatted}\n**ถึง:** {end_date_formatted}"
            line_bot_api.reply_message(event.reply_token,TextSendMessage(text=summary_message_text))
            del user_states[user_id]
            return

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

