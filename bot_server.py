# -*- coding: utf-8 -*-

from flask import Flask, request, abort, send_from_directory, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    DatetimePickerAction, PostbackEvent, PostbackAction, # เพิ่ม PostbackAction
    ImageSendMessage
)
import os
import json
from datetime import datetime, timedelta
import uuid

import firebase_admin
from firebase_admin import credentials, firestore

from dotenv import load_dotenv
load_dotenv() # สำหรับรันทดสอบบนเครื่องตัวเอง (Local)

try:
    from PIL import Image, ImageDraw, ImageFont
    # กำหนด Directory สำหรับ Fonts ชั่วคราว (จำเป็นสำหรับบางสภาพแวดล้อมที่ไม่มี Arial)
    # ใน Production อาจต้องแน่ใจว่ามี Font ที่รองรับภาษาไทย
    # ถ้าไม่มี font ที่รองรับภาษาไทย การวาดภาพอาจมีปัญหา
    FONT_PATH = "arial.ttf" # สมมติว่ามี arial.ttf หรือใช้ฟอนต์อื่นที่รองรับภาษาไทย
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None
    FONT_PATH = None
except Exception:
    # Handle Font not found error if we try to load it prematurely
    FONT_PATH = None

# --- ตั้งค่า LINE (แก้ไขแล้ว) ---
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")

app = Flask(__name__)

# ตรวจสอบว่ามี Token หรือไม่ก่อนสร้าง instance
if not CHANNEL_ACCESS_TOKEN or not CHANNEL_SECRET:
    app.logger.error("CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET must be set as environment variables.")
    line_bot_api = None
    handler = None
else:
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(CHANNEL_SECRET)

# --- เชื่อม Firebase ---
db = None
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
        app.logger.warning("FIREBASE_CREDENTIALS_JSON not found. Firebase not connected.")
except Exception as e:
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
LEAVE_TYPES = ["ลาพัก", "ลากิจ", "ลาป่วย", "ราชการ"]

# --- UTILITY FUNCTIONS ---

def _get_font(size):
    """Helper function to load font safely."""
    if ImageFont and FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except IOError:
            app.logger.warning(f"Font file {FONT_PATH} not found. Using default font.")
    if ImageFont:
        return ImageFont.load_default()
    return None

def save_leave_to_firestore(user_id, data):
    """Saves the leave request data to Firestore."""
    if not db:
        app.logger.error("Firestore client is not available.")
        return False
    
    # เพิ่ม timestamp และ ID ที่ไม่ซ้ำกันสำหรับรายการลา
    data['timestamp'] = firestore.SERVER_TIMESTAMP
    data['line_user_id'] = user_id
    data['status'] = 'Pending' # สถานะเริ่มต้น
    data['leave_id'] = str(uuid.uuid4()).split('-')[0].upper() # ใช้ ID สั้นๆ เพื่อความสะดวก
    data['submission_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        # บันทึกใน collection หลัก
        collection_ref = db.collection(u'line_bot_leave_records')
        collection_ref.document(data['leave_id']).set(data)
        app.logger.info(f"Leave record saved: {data['leave_id']}")
        return True
    except Exception as e:
        app.logger.error(f"Error saving to Firestore: {e}")
        return False

def generate_summary_image(data):
    """Generates a summary image of the leave request using PIL."""
    if Image is None or ImageDraw is None or ImageFont is None:
        app.logger.warning("Pillow not imported. Skipping image generation.")
        return None, None

    try:
        image_dir = '/tmp/line_bot_images'
        if not os.path.exists(image_dir):
            os.makedirs(image_dir)
        
        # File naming
        filename = f"leave_summary_{data['leave_id']}.png"
        filepath = os.path.join(image_dir, filename)
        # ใช้ url_for ใน Flask เพื่อสร้าง URL ที่ถูกต้อง
        image_url = url_for('serve_image', filename=filename, _external=True)

        # Image setup
        width, height = 650, 480
        img = Image.new('RGB', (width, height), color = '#F0F4F8') # Background color
        d = ImageDraw.Draw(img)
        
        # Load fonts
        font_title = _get_font(36)
        font_header = _get_font(24)
        font_body = _get_font(20)

        # Drawing box
        d.rectangle((20, 20, width - 20, height - 20), fill='#FFFFFF', outline='#007BFF', width=3)
        
        # Drawing title
        title_text = "ใบแจ้งลาอิเล็กทรอนิกส์"
        d.text((width/2, 40), title_text, fill=(25, 25, 112), font=font_title, anchor="mt") # midnight blue
        
        # Drawing lines
        lines = [
            ("ID รายการ:", data['leave_id']),
            ("ประเภทการลา:", data['leave_type']),
            ("ชื่อผู้ลา:", data['personnel_name']),
            ("วันที่เริ่มต้น:", data['start_date']),
            ("วันที่สิ้นสุด:", data['end_date']),
            ("รวมระยะเวลา:", f"{data['duration_days']} วัน"),
            ("วันที่ยื่นคำขอ:", data['submission_date'].split(' ')[0]),
            ("เหตุผล:", data['reason']),
            ("สถานะ:", "รอการอนุมัติ (Pending)")
        ]
        
        y_offset = 110
        line_height = 35
        for key, value in lines:
            d.text((50, y_offset), key, fill=(50, 50, 50), font=font_header)
            
            # Draw value right-aligned within a space
            text_bbox = d.textbbox((0, 0), key, font=font_header)
            x_key_end = 50 + (text_bbox[2] - text_bbox[0])
            
            d.text((x_key_end + 20, y_offset), value, fill=(0, 100, 0) if key == "สถานะ:" else (0, 0, 0), font=font_body)
            y_offset += line_height
            
        # Save image
        img.save(filepath)
        app.logger.info(f"Image generated at: {filepath}")
        
        return filepath, image_url
        
    except Exception as e:
        app.logger.error(f"Image generation failed: {e}")
        return None, None

def send_name_picker(reply_token, user_id):
    """Sends a Quick Reply set for personnel name selection."""
    name_buttons = [
        QuickReplyButton(action=MessageAction(label=name, text=name)) 
        for name in personnel_list
    ]
    name_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
    
    reply_msg = TextSendMessage(
        text="กรุณาเลือกชื่อกำลังพลที่ต้องการลาครับ (เลื่อนเพื่อดูชื่อเพิ่มเติม):",
        quick_reply=QuickReply(items=name_buttons)
    )
    line_bot_api.reply_message(reply_token, reply_msg)


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
        app.logger.error("Invalid signature received.")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error handling webhook: {e}")
        abort(500)
    return 'OK'

# --- Message Event Handler ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    if not line_bot_api:
        return # ไม่ทำงานถ้า line_bot_api ไม่ถูกสร้าง
        
    user_id = event.source.user_id
    user_message = event.message.text

    # --- Global Command Handling ---
    if user_message == "#แจ้งลา":
        if user_id in user_states: del user_states[user_id] # Clear previous state if any
        user_states[user_id] = {"step": "awaiting_leave_type", "data": {}}
        leave_buttons = [
            QuickReplyButton(action=MessageAction(label=lt, text=lt)) for lt in LEAVE_TYPES
        ]
        leave_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
        
        reply_msg = TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=QuickReply(items=leave_buttons))
        line_bot_api.reply_message(event.reply_token, reply_msg)
        return

    elif user_message == "#รีเซ็ต":
        if user_id in user_states: del user_states[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔄️ รีเซ็ตสถานะการทำรายการเรียบร้อยแล้วครับ"))
        return

    elif user_message == "#ยกเลิก": # Handle cancellation
        if user_id in user_states:
            del user_states[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ยกเลิกการแจ้งลาเรียบร้อยแล้วครับ"))
        else:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่พบรายการที่กำลังดำเนินการอยู่ครับ"))
        return
    
    # --- State-driven processing ---
    if user_id in user_states:
        current_step = user_states[user_id]['step']
        data = user_states[user_id]['data']
        
        # STEP 1: Awaiting Leave Type (Message from Quick Reply)
        if current_step == "awaiting_leave_type":
            if user_message in LEAVE_TYPES:
                data['leave_type'] = user_message
                user_states[user_id]['step'] = "awaiting_start_date"
                
                # Transition to Date Picker (Start Date) - Postback is expected next
                quick_reply_items = [
                    QuickReplyButton(action=DatetimePickerAction(
                        label="🗓️ เลือกวันเริ่มต้น",
                        data="set_start_date",
                        mode="date"
                    )),
                    QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
                ]
                reply_msg = TextSendMessage(
                    text=f"ประเภท: **{user_message}**\nกรุณาเลือกวันเริ่มต้นการลาครับ (ใช้ปฏิทินด้านล่าง)", 
                    quick_reply=QuickReply(items=quick_reply_items)
                )
                line_bot_api.reply_message(event.reply_token, reply_msg)
                return
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ กรุณาเลือกประเภทการลาจากปุ่มที่กำหนดครับ"))
                return

        # STEP 3: Awaiting Reason (Text Input)
        elif current_step == "awaiting_reason":
            if len(user_message.strip()) < 5:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาพิมพ์เหตุผลการลาที่ชัดเจนและยาวกว่า 5 ตัวอักษรครับ"))
                return

            data['reason'] = user_message.strip()
            user_states[user_id]['step'] = "awaiting_name"
            
            # Transition to Name Picker
            send_name_picker(event.reply_token, user_id) 
            return

        # STEP 4: Awaiting Name (Message from Quick Reply)
        elif current_step == "awaiting_name":
            if user_message in personnel_list:
                data['personnel_name'] = user_message
                user_states[user_id]['step'] = "awaiting_confirmation"
                
                # Transition to Confirmation 
                confirm_buttons = [
                    QuickReplyButton(action=PostbackAction(label="✅ ยืนยันการแจ้งลา", data="confirm_leave")),
                    QuickReplyButton(action=MessageAction(label="แก้ไขเหตุผล", text="แก้ไขเหตุผล")),
                    QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
                ]
                
                summary_text = (
                    "สรุปรายการแจ้งลา:\n"
                    f"ประเภท: {data.get('leave_type', '-')}\n"
                    f"ชื่อผู้ลา: {data.get('personnel_name', '-')}\n"
                    f"เริ่มต้น: {data.get('start_date', '-')}\n"
                    f"สิ้นสุด: {data.get('end_date', '-')}\n"
                    f"รวม: {data.get('duration_days', '-')} วัน\n"
                    f"เหตุผล: {data.get('reason', '-')}"
                )
                
                reply_msg = TextSendMessage(text=summary_text, quick_reply=QuickReply(items=confirm_buttons))
                line_bot_api.reply_message(event.reply_token, reply_msg)
                return
            elif user_message == "แก้ไขเหตุผล":
                user_states[user_id]['step'] = "awaiting_reason"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาพิมพ์เหตุผลการลาใหม่ครับ:"))
                return
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ กรุณาเลือกชื่อจากปุ่มที่กำหนดครับ"))
                return
        
        # If any other text message is received while in a flow, remind the user
        elif current_step.startswith("awaiting"):
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"🤖 ขณะนี้คุณกำลังอยู่ในขั้นตอน '{current_step.replace('awaiting_', '')}' กรุณาดำเนินการต่อ หรือพิมพ์ #ยกเลิก ครับ"))
            return

# --- Postback Event Handler ---
@handler.add(PostbackEvent)
def handle_postback(event):
    if not line_bot_api: return
    
    user_id = event.source.user_id
    data_postback = event.postback.data
    
    if user_id not in user_states:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🤖 กรุณาพิมพ์ #แจ้งลา เพื่อเริ่มต้นการทำรายการใหม่ครับ"))
        return

    current_step = user_states[user_id]['step']
    data_state = user_states[user_id]['data']

    # --- Start Date Selection (set_start_date) ---
    if data_postback == "set_start_date" and current_step == "awaiting_start_date":
        date_str = event.postback.params['date']
        data_state['start_date'] = date_str
        user_states[user_id]['step'] = "awaiting_end_date"
        
        # Transition to End Date Picker
        quick_reply_items = [
            QuickReplyButton(action=DatetimePickerAction(
                label="🗓️ เลือกวันสิ้นสุด",
                data="set_end_date",
                mode="date",
                initial=date_str # Suggest the start date as initial date
            )),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ]
        
        reply_msg = TextSendMessage(
            text=f"วันเริ่มต้น: **{date_str}**\nกรุณาเลือกวันสิ้นสุดการลาครับ",
            quick_reply=QuickReply(items=quick_reply_items)
        )
        line_bot_api.reply_message(event.reply_token, reply_msg)
        return

    # --- End Date Selection (set_end_date) ---
    elif data_postback == "set_end_date" and current_step == "awaiting_end_date":
        end_date_str = event.postback.params['date']
        start_date_str = data_state.get('start_date')
        
        if not start_date_str:
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาด ไม่พบวันเริ่มต้น กรุณาพิมพ์ #แจ้งลา ใหม่ครับ"))
             del user_states[user_id]
             return
        
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        if end_date < start_date:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น กรุณาเลือกใหม่ครับ"))
            # Prompt the user again to select end date
            quick_reply_items = [
                QuickReplyButton(action=DatetimePickerAction(
                    label="🗓️ เลือกวันสิ้นสุด",
                    data="set_end_date",
                    mode="date",
                    initial=start_date_str
                )),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ]
            reply_msg = TextSendMessage(
                text=f"วันเริ่มต้น: **{start_date_str}**\nกรุณาเลือกวันสิ้นสุดการลาครับ",
                quick_reply=QuickReply(items=quick_reply_items)
            )
            line_bot_api.push_message(user_id, reply_msg)
            return
            
        # Calculate duration (inclusive: day 1 to day 3 is 3 days)
        duration = (end_date - start_date).days + 1
        
        data_state['end_date'] = end_date_str
        data_state['duration_days'] = duration
        user_states[user_id]['step'] = "awaiting_reason"
        
        # Transition to Reason input
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"🗓️ ระยะเวลาลา **{start_date_str}** ถึง **{end_date_str}** รวม **{duration} วัน**\n\nกรุณาพิมพ์เหตุผลในการลาครับ"
        ))
        return

    # --- Confirmation (confirm_leave) ---
    elif data_postback == "confirm_leave" and current_step == "awaiting_confirmation":
        # 1. Save to Firestore
        data_to_save = data_state
        save_successful = save_leave_to_firestore(user_id, data_to_save)
        
        if not save_successful:
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการบันทึกข้อมูล (Firestore) กรุณาลองใหม่อีกครั้งครับ"))
             return

        # 2. Generate Image Summary
        image_path, image_url = generate_summary_image(data_to_save)
        
        # 3. Send final message and image
        if image_path and image_url:
            summary_text = f"✅ บันทึกการลาเรียบร้อยแล้ว (ID: {data_to_save['leave_id']})\nรายละเอียดตามรูปภาพด้านล่างนี้ครับ"
            image_message = ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
            line_bot_api.reply_message(event.reply_token, [
                TextSendMessage(text=summary_text),
                image_message
            ])
        else:
            # Fallback if image generation fails
             line_bot_api.reply_message(event.reply_token, TextSendMessage(
                text=f"✅ บันทึกการลาเรียบร้อยแล้ว (ID: {data_to_save['leave_id']})\n\n[ไม่สามารถสร้างรูปภาพสรุปได้]\n" + 
                     f"ประเภท: {data_to_save['leave_type']}\n" + 
                     f"ชื่อ: {data_to_save['personnel_name']}\n" +
                     f"วันที่: {data_to_save['start_date']} - {data_to_save['end_date']}\n" +
                     f"รวม: {data_to_save['duration_days']} วัน\n" +
                     f"เหตุผล: {data_to_save['reason']}"
            ))

        # 4. Clear state
        del user_states[user_id]
        return


# --- Run Server ---
if __name__ == "__main__":
    # Ensure temporary image directory exists on startup (for local testing)
    image_dir = '/tmp/line_bot_images'
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
