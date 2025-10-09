# app.py - ฉบับสมบูรณ์สำหรับ Developer และ Render Deployment
import os
import json
import uuid
from flask import Flask, request, abort, url_for, send_from_directory
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, PostbackEvent, TextMessage, TextSendMessage, TemplateSendMessage,
    CarouselTemplate, CarouselColumn, PostbackAction, QuickReply, QuickReplyButton,
    DatetimePickerAction, ImageSendMessage, MessageAction
)
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore import FieldFilter
from datetime import datetime, timedelta, date
# --- Configuration and Initialization ---
# Environment variables (ต้องตั้งค่าใน Render)
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")

app = Flask(__name__)

# 🌟 Admin Configuration 🌟
# ใช้สำหรับระบุ Line ID ของผู้ดูแลระบบเพื่อเข้าถึงคำสั่งพิเศษ
ADMIN_LINE_ID = os.getenv("ADMIN_LINE_ID", "max466123")  

# LINE API setup
line_bot_api = None
handler = None
if CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET:
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(CHANNEL_SECRET)
else:
    app.logger.error("FATAL: LINE credentials not set. Webhook will fail.")

# Firebase setup
db = None
try:
    if FIREBASE_CREDENTIALS_JSON:
        cred_dict = json.loads(FIREBASE_CREDENTIALS_JSON)
        cred = credentials.Certificate(cred_dict)
        
        # ป้องกัน initialize ซ้ำเมื่อ Gunicorn Fork Process
        if not firestore._apps:
            initialize_app(cred)
            
        db = firestore.client()
        app.logger.info("Firebase connected successfully.")
    else:
        app.logger.warning("FIREBASE_CREDENTIALS_JSON not set. Firebase functions will fail.")
except Exception as e:
    app.logger.error(f"FATAL: Error initializing Firebase: {e}")

# Image setup (Requires Pillow and a Thai font)
try:
    from PIL import Image, ImageDraw, ImageFont
    IMAGE_DIR = "/tmp/line_bot_images"
    os.makedirs(IMAGE_DIR, exist_ok=True)
    
    # --- FONT FIX: ต้องแน่ใจว่าไฟล์ Sarabun-Regular.ttf อยู่ใน Root Directory ของโปรเจกต์ ---
    FONT_FILENAME = "Sarabun-Regular.ttf"  
    FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)
    
    # ทดสอบโหลดฟอนต์ในช่วงเริ่มต้น หากล้มเหลวจะใช้ FONT_PATH = None
    try:
        ImageFont.truetype(FONT_PATH, 1) 
        app.logger.info(f"Custom font loaded successfully from {FONT_PATH}.")
    except IOError:
        FONT_PATH = None
        app.logger.warning(f"Custom font file '{FONT_FILENAME}' not found. Using default font.")
    # --- END OF FONT FIX ---
        
except ImportError:
    Image, ImageDraw, ImageFont, FONT_PATH = None, None, None, None
    app.logger.warning("Pillow not installed. Image generation disabled.")

# Constants
PERSONNEL_COLLECTION = "personnel"
DUTY_COLLECTION = "duty_rotation"
LEAVE_COLLECTION = "line_duty_leave"  
SESSION_COLLECTION = "user_sessions" # ใช้สำหรับเก็บสถานะแทน user_states = {}
DUTY_LOGS_COLLECTION = "duty_logs" # คอลเลกชันใหม่สำหรับบันทึกการเข้า-ออกเวร
LEAVE_TYPES = ["ลาพัก", "ลากิจ", "ลาป่วย", "ราชการ"]

# --- UTILITY & DATA FUNCTIONS (State Management) ---
def get_session_state(user_id):
    """Retrieves the user's current session state from Firestore."""
    if not db: return None
    try:
        doc = db.collection(SESSION_COLLECTION).document(user_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        app.logger.error(f"Error fetching session for {user_id}: {e}")
        return None

def save_session_state(user_id, step, data):
    """Saves the user's current session state to Firestore."""
    if not db: return False
    try:
        db.collection(SESSION_COLLECTION).document(user_id).set({
            "step": step,
            "data": data,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        return True
    except Exception as e:
        app.logger.error(f"Error saving session for {user_id}: {e}")
        return False

def clear_session_state(user_id):
    """Clears the user's session state from Firestore."""
    if not db: return
    try:
        db.collection(SESSION_COLLECTION).document(user_id).delete()
    except Exception as e:
        app.logger.error(f"Error clearing session for {user_id}: {e}")

# --- UTILITY & DATA FUNCTIONS (General) ---
def is_admin(user_id):
    """Checks if the user ID is the configured admin ID."""
    return user_id == ADMIN_LINE_ID

def _get_font(size):
    """Helper function to load font safely."""
    if ImageFont and FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except IOError:
            app.logger.warning(f"Error loading TrueType font from {FONT_PATH}. Using default font.")
    if ImageFont:
        return ImageFont.load_default()
    return None

def get_personnel_data():
    """Retrieves all personnel data from Firestore."""
    if not db: return []
    try:
        docs = db.collection(PERSONNEL_COLLECTION).stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        app.logger.error(f"Error fetching personnel data: {e}")
        return []

def get_personnel_names():
    """Retrieves a list of all personnel names."""
    return [p.get('name') for p in get_personnel_data() if p.get('name')]

def get_duty_by_date(date_str):
    """Calculates duty assignment for a given date using Firestore data."""
    personnel = get_personnel_data()
    if not personnel or not db: return None
    
    # กรองกำลังพลที่ลาในวันนี้ออกก่อน
    leave_list = get_leaves_on_date(date_str)
    
    # สร้าง Map: ชื่อกำลังพล -> สถานะการลา
    leave_map = {leave['personnel_name']: leave['leave_type'] for leave in leave_list}

    # กรองกำลังพลที่ไม่ลา และเรียงลำดับตาม duty_priority
    available_personnel = [p for p in personnel if p.get('name') not in leave_map]
    if not available_personnel: 
        return [] # ไม่มีใครอยู่
    
    available_personnel.sort(key=lambda x: x.get("duty_priority", 999))
    num_personnel = len(available_personnel)
    
    # ดึงรูปแบบเวรจาก Firestore
    duty_defs = []
    try:
        docs = db.collection(DUTY_COLLECTION).order_by("priority").stream()
        duty_defs = [doc.to_dict() for doc in docs]
    except Exception as e:
        app.logger.error(f"Error fetching duty rotation data: {e}")
        return None
    if not duty_defs: return None
    
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
        
    # Rotation Logic (Assuming reference date is 2024-01-01)
    reference_date = date(2024, 1, 1)
    day_diff = (date_obj - reference_date).days
    
    duty_assignments = []
    
    # 1. จัดเวรให้กำลังพลที่อยู่
    for i, duty_info in enumerate(duty_defs):
        # ใช้ดัชนีหมุนเวียนกับกำลังพลที่อยู่
        person_index = (day_diff + i) % num_personnel
        person = available_personnel[person_index]
        duty_assignments.append({
            "duty": duty_info.get("duty_name", "Duty N/A"), 
            "name": person.get("name", "Name N/A"), 
            "color": duty_info.get("color", "#000000"),
            "status": "ปฏิบัติงาน"
        })
    
    # 2. เพิ่มกำลังพลที่ลาเข้ามาในรายการ (เพื่อแสดงให้ครบ)
    for name, leave_type in leave_map.items():
        duty_assignments.append({
            "duty": f"ลา ({leave_type})",
            "name": name,
            "color": "#FF0000",
            "status": "ลา"
        })
        
    return duty_assignments

def get_leaves_on_date(date_str):
    """Retrieves approved leave data that covers the given date."""
    if not db: return []
    try:
        # ดึงรายการที่อนุมัติแล้วและมีวันเริ่มต้น/สิ้นสุดใกล้เคียง
        # หมายเหตุ: Firestore ไม่รองรับการ Query ช่วงวันที่ที่ซับซ้อนโดยตรง (ต้องใช้ >= และ <= ใน Field เดียวกัน)
        # ดังนั้นจะ Query แบบกว้างๆ แล้วกรองใน Python
        date_query = datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
        
        # ดึงรายการลาที่อนุมัติแล้วทั้งหมด
        docs = db.collection(LEAVE_COLLECTION).where(filter=FieldFilter("status", "==", "อนุมัติ")).stream()
        all_approved_leaves = [doc.to_dict() for doc in docs]
        
        # กรองใน Python
        leaves_on_date = []
        target_date = datetime.strptime(date_query, '%Y-%m-%d').date()
        for leave in all_approved_leaves:
            try:
                start = datetime.strptime(leave.get('start_date'), '%Y-%m-%d').date()
                end = datetime.strptime(leave.get('end_date'), '%Y-%m-%d').date()
                if start <= target_date <= end:
                    leaves_on_date.append(leave)
            except ValueError:
                # Handle invalid date format in DB
                continue
                
        return leaves_on_date
    except Exception as e:
        app.logger.error(f"Error fetching leaves on date {date_str}: {e}")
        return []

def save_leave_to_firestore(line_id, data):
    """Saves the final leave request data to Firestore."""
    if not db: return False
    try:
        doc_ref = db.collection(LEAVE_COLLECTION).document()
        data.update({
            "line_id": line_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": 'Pending',  
            "doc_id": doc_ref.id,  
            "submission_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        doc_ref.set(data)
        return True
    except Exception as e:
        app.logger.error(f"Error saving leave to Firestore: {e}")
        return False

def get_duty_log_for_today(name, log_type):
    """Checks if a log_type (checkin/checkout) exists for today for a given personnel name."""
    if not db: return None
    today_str = datetime.now().strftime('%Y-%m-%d')
    try:
        query = db.collection(DUTY_LOGS_COLLECTION).where(filter=FieldFilter("name", "==", name)).where(filter=FieldFilter("date", "==", today_str)).where(filter=FieldFilter("log_type", "==", log_type)).limit(1).stream()
        docs = list(query)
        return docs[0].to_dict() if docs else None
    except Exception as e:
        app.logger.error(f"Error checking duty log: {e}")
        return None

def log_duty_action(user_id, name, log_type):
    """Logs the check-in or check-out action to Firestore."""
    if not db: return False
    today_str = datetime.now().strftime('%Y-%m-%d')
    time_str = datetime.now().strftime('%H:%M:%S')
    
    # ตรวจสอบว่ามีการลงเวลาไปแล้วหรือยัง
    existing_log = get_duty_log_for_today(name, log_type)
    if existing_log:
        return False, f"คุณได้ลงเวลา{log_type}แล้วเมื่อ {existing_log.get('time', 'N/A')} วันนี้"
    
    # ตรวจสอบเวร
    assignments = get_duty_by_date(today_str)
    on_duty_names = [a['name'] for a in assignments if a['status'] == 'ปฏิบัติงาน']
    
    if name not in on_duty_names:
        return False, f"⚠️ คุณ {name} ไม่ได้มีเวรประจำวันนี้"

    # บันทึก
    try:
        db.collection(DUTY_LOGS_COLLECTION).add({
            "line_id": user_id,
            "name": name,
            "date": today_str,
            "time": time_str,
            "log_type": log_type,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        return True, f"✅ บันทึกเวลา{log_type}สำเร็จ เวลา {time_str}"
    except Exception as e:
        app.logger.error(f"Error saving duty log: {e}")
        return False, "❌ ข้อผิดพลาดในการบันทึก Duty Log (Firestore)"


def generate_summary_image(data):
    """Generates a summary image of the leave request using PIL."""
    if Image is None:
        return None, None
        
    try:
        image_dir = IMAGE_DIR
        filename = f"leave_summary_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(image_dir, filename)
        
        # ⚠️ ต้องแน่ใจว่า Render service มีการตั้งค่า "External URL" ที่ถูกต้อง
        image_url = url_for('serve_image', filename=filename, _external=True) 
        
        width, height = 650, 480
        img = Image.new('RGB', (width, height), color = '#F0F4F8') 
        d = ImageDraw.Draw(img)
        
        font_title = _get_font(36)
        font_header = _get_font(24)
        font_body = _get_font(20)
        
        d.rectangle((20, 20, width - 20, height - 20), fill='#FFFFFF', outline='#007BFF', width=3)
        title_text = "ใบแจ้งลาอิเล็กทรอนิกส์"
        # ใช้ d.text() กับ anchor="mt" ได้ถ้าใช้ PIL เวอร์ชันใหม่ (>= 9.2.0)
        d.text((width/2, 40), title_text, fill=(25, 25, 112), font=font_title, anchor="mt") 
        
        lines = [
            ("ประเภทการลา:", data['leave_type']),
            ("ชื่อผู้ลา:", data['personnel_name']),
            ("วันที่เริ่มต้น:", data['start_date']),
            ("วันที่สิ้นสุด:", data['end_date']),
            ("รวมระยะเวลา:", f"{data['duration_days']} วัน"),
            ("เหตุผล:", data['reason']),
            ("สถานะ:", "รอการอนุมัติ (Pending)")
        ]
        
        y_offset = 110
        line_height = 40
        for key, value in lines:
            d.text((50, y_offset), key, fill=(50, 50, 50), font=font_header)
            d.text((width/2, y_offset), value, fill=(0, 0, 0), font=font_body, anchor="lm")
            y_offset += line_height
            
        img.save(filepath)
        return filepath, image_url
    except Exception as e:
        app.logger.error(f"Image generation failed: {e}")
        return None, None

def send_duty_message(reply_token, date_str, assignments):
    """Sends a summary of duty assignments, including leave and duty logs."""
    if not assignments:
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"ไม่พบข้อมูลเวรสำหรับวันที่ {date_str}"))
        return
        
    summary = f"🗓️ **เวรประจำวันที่ {date_str}**\n\n"
    duty_count = 0
    leave_count = 0
    
    for item in assignments:
        log_type_label = ""
        log_type_text = ""
        
        if item['status'] == 'ปฏิบัติงาน':
            log_in = get_duty_log_for_today(item['name'], 'checkin')
            log_out = get_duty_log_for_today(item['name'], 'checkout')
            
            if log_in:
                log_type_label = "✅ เข้า"
                log_type_text = f" ({log_in.get('time', '-')})"
            
            if log_out:
                log_type_label = "❌ ออก"
                log_type_text = f" ({log_out.get('time', '-')})"

            if log_in and log_out:
                 log_type_label = "💯 ครบ"
                 log_type_text = f" ({log_in.get('time', '-')}-{log_out.get('time', '-')})"
            elif log_in and not log_out:
                 log_type_label = "⏳ ปฏิบัติงาน"
            elif not log_in and not log_out:
                 log_type_label = "❗ ยังไม่เข้า"
            
            summary += f"▶️ {item['duty']}: **{item['name']}** [{log_type_label}{log_type_text}]\n"
            duty_count += 1
        elif item['status'] == 'ลา':
            summary += f"🌴 {item['duty']}: *{item['name']}*\n"
            leave_count += 1
        
    line_bot_api.reply_message(reply_token, TextSendMessage(text=summary))

# --- ADMIN HANDLERS ---
# (Admin Handlers เหมือนเดิม)

def handle_admin_command(event, text):
    """Handles commands exclusively for the admin."""
    command = text.lower().split()
    reply_token = event.reply_token
    
    if len(command) == 1 or command[1] == "help":
        help_text = (
            "🛠️ **Admin Commands**\n"
            "• `admin leave` : ดูรายการลาที่รอการอนุมัติ\n"
            "• (การจัดการข้อมูลกำลังพลและเวรทำผ่าน Firebase Console)"
        )
        line_bot_api.reply_message(reply_token, TextSendMessage(text=help_text))
        return
    elif command[1] == "leave":
        send_pending_leaves(reply_token)
        return
        
    else:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="ไม่พบคำสั่ง Admin นี้ พิมพ์ `admin help`"))

def send_pending_leaves(reply_token):
    """Fetches and sends a Carousel of pending leave requests for approval."""
    if not db: 
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ Firebase ไม่พร้อมใช้งาน"))
        return
        
    try:
        docs = db.collection(LEAVE_COLLECTION).where(filter=FieldFilter("status", "==", "Pending")).stream()
        pending_leaves = [doc.to_dict() for doc in docs]
    except Exception as e:
        app.logger.error(f"Error querying pending leaves: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ เกิดข้อผิดพลาดในการดึงรายการลา"))
        return

    columns = []
    if pending_leaves:
        for leave in pending_leaves[:10]:
            doc_id = leave.get('doc_id')  
            
            column = CarouselColumn(
                title=f"⏳ {leave.get('leave_type')}",
                text=f"{leave.get('personnel_name')}\n{leave.get('start_date')} ถึง {leave.get('end_date')} ({leave.get('duration_days')} วัน)",
                actions=[
                    PostbackAction(label="✔️ อนุมัติ", data=f"action=approve_leave&doc_id={doc_id}"),
                    PostbackAction(label="❌ ไม่อนุมัติ", data=f"action=reject_leave&doc_id={doc_id}"),
                ]
            )
            columns.append(column)
            
        line_bot_api.reply_message(
            reply_token,
            TemplateSendMessage(
                alt_text=f"มี {len(pending_leaves)} รายการลาที่รออนุมัติ",
                template=CarouselTemplate(columns=columns)
            )
        )
    else:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="✅ ไม่มีรายการลาที่รอการอนุมัติ"))


# --- FLASK ROUTES (เหมือนเดิม) ---
@app.route("/images/<filename>")
def serve_image(filename):
    """Serves generated images from the /tmp directory."""
    try:
        return send_from_directory(IMAGE_DIR, filename)
    except Exception as e:
        app.logger.error(f"Error serving image {filename}: {e}")
        abort(404)

@app.route("/webhook", methods=['POST'])
def webhook():
    """Main LINE Webhook Handler."""
    if not handler or not line_bot_api or not db:
        app.logger.error("Service not ready (LINE/Firebase). Check environment variables.")
        return "Service Not Ready", 503  
        
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
        # Log error details but return OK to prevent LINE from retrying excessively
        return 'OK'  
        
    return 'OK'

# --- MESSAGE HANDLER (รวม Check-in/out) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # 🌟 Admin Check 🌟
    if is_admin(user_id) and text.lower().startswith("admin"):
        handle_admin_command(event, text)
        return
    
    # --- User Commands ---
    if text in ["ลา", "ขอลา", "#แจ้งลา"]:
        # Initiate/Restart leave request flow
        clear_session_state(user_id)  
        save_session_state(user_id, "awaiting_leave_type", {})
        
        leave_buttons = [QuickReplyButton(action=MessageAction(label=lt, text=lt)) for lt in LEAVE_TYPES]
        leave_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
        
        reply_msg = TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=QuickReply(items=leave_buttons))
        line_bot_api.reply_message(reply_token, reply_msg)
        return
    
    elif text in ["เวร", "เวรวันนี้", "#เวร"]:
        date_today = datetime.now().strftime("%Y-%m-%d")
        assignments = get_duty_by_date(date_today)
        send_duty_message(reply_token, date_today, assignments)
        return
        
    elif text == "#ยกเลิก":
        clear_session_state(user_id)
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ ยกเลิกการทำรายการเรียบร้อยแล้วครับ"))
        return
        
    # --- NEW: Check-in / Check-out Commands ---
    elif text in ["เข้าเวร", "#เข้าเวร"]:
        clear_session_state(user_id)
        save_session_state(user_id, "awaiting_checkin_name", {"action": "checkin"})
        
        name_buttons = [QuickReplyButton(action=MessageAction(label=name, text=name)) for name in get_personnel_names()]
        name_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
        
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="🕒 บันทึกเวลาเข้าเวร: กรุณาเลือกชื่อกำลังพล", quick_reply=QuickReply(items=name_buttons))
        )
        return
        
    elif text in ["ออกเวร", "#ออกเวร"]:
        clear_session_state(user_id)
        save_session_state(user_id, "awaiting_checkout_name", {"action": "checkout"})
        
        name_buttons = [QuickReplyButton(action=MessageAction(label=name, text=name)) for name in get_personnel_names()]
        name_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
        
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="🛑 บันทึกเวลาออกเวร: กรุณาเลือกชื่อกำลังพล", quick_reply=QuickReply(items=name_buttons))
        )
        return
    
    # --- State-Driven Input (Awaiting Type, Reason, Name, Duty Log Name) ---
    session_state = get_session_state(user_id)
    if session_state:
        current_step = session_state['step']
        data_state = session_state['data']
        personnel_names = get_personnel_names()

        # --- Leave Request Flow Steps ---
        if current_step == "awaiting_leave_type" and text in LEAVE_TYPES:
            # Step 1: Leave Type selected -> move to date picker (Postback handles date)
            data_state['leave_type'] = text
            save_session_state(user_id, "awaiting_start_date", data_state)
            quick_reply_items = [
                QuickReplyButton(action=DatetimePickerAction(label="🗓️ เลือกวันเริ่มต้น", data="set_start_date", mode="date", initial=datetime.now().strftime('%Y-%m-%d'))),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ]
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=f"ประเภทการลา: **{text}**\nกรุณาเลือกวันเริ่มต้นการลาครับ", 
                quick_reply=QuickReply(items=quick_reply_items)
            ))
            return

        elif current_step == "awaiting_reason":
            # Step 4: Reason entered -> move to name selection
            if len(text.strip()) < 5:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="กรุณาพิมพ์เหตุผลการลาที่ชัดเจนและยาวกว่า 5 ตัวอักษรครับ"))
                return
            data_state['reason'] = text.strip()
            save_session_state(user_id, "awaiting_name", data_state)
            
            name_buttons = [QuickReplyButton(action=MessageAction(label=name, text=name)) for name in personnel_names]
            name_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))
            
            line_bot_api.reply_message(
                reply_token, 
                TextSendMessage(text="กรุณาเลือกชื่อกำลังพลที่ต้องการลาครับ:", quick_reply=QuickReply(items=name_buttons))
            )
            return
            
        elif current_step == "awaiting_name" and text in personnel_names:
            # Step 5: Name selected -> move to confirmation (Postback handles confirmation)
            data_state['personnel_name'] = text
            save_session_state(user_id, "awaiting_confirmation", data_state)
            
            summary_text = (
                "สรุปรายการแจ้งลา:\n"
                f"ประเภท: {data_state.get('leave_type', '-')}\n"
                f"ชื่อผู้ลา: {data_state.get('personnel_name', '-')}\n"
                f"เริ่มต้น: {data_state.get('start_date', '-')}\n"
                f"สิ้นสุด: {data_state.get('end_date', '-')}\n"
                f"รวม: {data_state.get('duration_days', '-')} วัน\n"
                f"เหตุผล: {data_state.get('reason', '-')}"
            )
            confirm_buttons = [
                QuickReplyButton(action=PostbackAction(label="✅ ยืนยันการแจ้งลา", data="action=confirm_leave")),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ]
            line_bot_api.reply_message(reply_token, TextSendMessage(text=summary_text, quick_reply=QuickReply(items=confirm_buttons)))
            return

        # --- NEW: Duty Check-in/Check-out Flow Steps ---
        elif current_step == "awaiting_checkin_name" and text in personnel_names:
            # Check-in Name selected -> log the action
            success, message = log_duty_action(user_id, text, 'checkin')
            clear_session_state(user_id)
            
            # 💡 NEW: แสดงเวรวันนี้เพื่อให้ผู้ใช้เห็นสถานะที่อัปเดต
            date_today = datetime.now().strftime("%Y-%m-%d")
            assignments = get_duty_by_date(date_today)
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=message))
            send_duty_message(reply_token, date_today, assignments) # ส่งข้อความเวรอีกครั้ง
            return
            
        elif current_step == "awaiting_checkout_name" and text in personnel_names:
            # Check-out Name selected -> log the action
            success, message = log_duty_action(user_id, text, 'checkout')
            clear_session_state(user_id)
            
            # 💡 NEW: แสดงเวรวันนี้เพื่อให้ผู้ใช้เห็นสถานะที่อัปเดต
            date_today = datetime.now().strftime("%Y-%m-%d")
            assignments = get_duty_by_date(date_today)
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=message))
            send_duty_message(reply_token, date_today, assignments) # ส่งข้อความเวรอีกครั้ง
            return
            
        # General Reminder if user sends message during Postback steps
        elif current_step.startswith("awaiting"):
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🤖 ขณะนี้คุณกำลังอยู่ในขั้นตอน '{current_step.replace('awaiting_', '')}' กรุณาดำเนินการต่อ หรือพิมพ์ #ยกเลิก ครับ"))
            return
            
    # --- Default Reply (เมนูหลักสำหรับผู้ใช้) ---
    else:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(
                text="🤖 **เมนูหลัก**\nคุณต้องการทำรายการใดครับ?",
                quick_reply=QuickReply(
                    items=[
                        QuickReplyButton(action=MessageAction(label="🗓️ เวรวันนี้", text="#เวร")),
                        QuickReplyButton(action=MessageAction(label="📝 แจ้งลา", text="#แจ้งลา")),
                        QuickReplyButton(action=MessageAction(label="🕒 เข้าเวร", text="#เข้าเวร")),
                        QuickReplyButton(action=MessageAction(label="🛑 ออกเวร", text="#ออกเวร")),
                    ]
                )
            )
        )

# --- POSTBACK HANDLER (เหมือนเดิม + ปรับปรุง) ---
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # Parse Postback Data (key=value&key2=value2)
    params = {}
    try:
        for item in data.split('&'):
            key, value = item.split('=', 1)
            params[key] = value
    except ValueError:
        return line_bot_api.reply_message(reply_token, TextSendMessage(text="ขออภัย ข้อมูลปุ่มไม่ถูกต้อง"))
        
    action = params.get('action')
    
    # 🌟 Admin Approval Actions 🌟
    if action in ["approve_leave", "reject_leave"] and is_admin(user_id):
        doc_id = params.get('doc_id')
        status = "อนุมัติ" if action == "approve_leave" else "ไม่อนุมัติ"
        
        try:
            doc_ref = db.collection(LEAVE_COLLECTION).document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                doc_data = doc.to_dict()
                doc_ref.update({"status": status, "reviewed_by": user_id, "review_timestamp": firestore.SERVER_TIMESTAMP})
                
                # Push Message to the user who submitted the leave
                push_text = f"✅ คำขอลา{doc_data.get('leave_type', '')} ของ {doc_data.get('personnel_name', 'N/A')} (วันที่ {doc_data.get('start_date', 'N/A')}) ได้รับการ**{status}**แล้ว"
                line_bot_api.push_message(doc_data.get('line_id', user_id), TextSendMessage(text=push_text))
                
                return line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ อัปเดตสถานะของ {doc_data.get('personnel_name', 'N/A')} เป็น **{status}**"))
            else:
                return line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ ไม่พบรายการลาที่ต้องการอัปเดต"))
        except Exception as e:
            app.logger.error(f"Error in Admin Approval: {e}")
            return line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ ข้อผิดพลาดในการอัปเดต: {e}"))
            
    # --- User State-Driven Actions (Date Picker & Confirmation) ---
    session_state = get_session_state(user_id)
    if not session_state:
        return line_bot_api.reply_message(reply_token, TextSendMessage(text="🤖 กรุณาพิมพ์ #แจ้งลา เพื่อเริ่มต้นการทำรายการใหม่ครับ"))
        
    current_step = session_state['step']
    data_state = session_state['data']
    date_str = event.postback.params.get('date') if event.postback.params else None
    
    # STEP 2: Start Date Selection (set_start_date)
    if params.get('data') == "set_start_date" and current_step == "awaiting_start_date" and date_str:
        data_state['start_date'] = date_str
        save_session_state(user_id, "awaiting_end_date", data_state)
        
        quick_reply_items = [
            QuickReplyButton(action=DatetimePickerAction(label="🗓️ เลือกวันสิ้นสุด", data="set_end_date", mode="date", initial=date_str)),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ]
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=f"วันเริ่มต้น: **{date_str}**\nกรุณาเลือกวันสิ้นสุดการลาครับ",
            quick_reply=QuickReply(items=quick_reply_items)
        ))
        return
        
    # STEP 3: End Date Selection (set_end_date)
    elif params.get('data') == "set_end_date" and current_step == "awaiting_end_date" and date_str:
        start_date_str = data_state.get('start_date')
        if not start_date_str: 
            clear_session_state(user_id)
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาด ไม่พบวันเริ่มต้น กรุณาพิมพ์ #แจ้งลา ใหม่ครับ"))
            
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        if end_date < start_date:
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น กรุณาเลือกใหม่ครับ"))
            
        data_state['end_date'] = date_str
        data_state['duration_days'] = (end_date - start_date).days + 1
        save_session_state(user_id, "awaiting_reason", data_state)
        
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=f"🗓️ ระยะเวลาลา **{start_date_str}** ถึง **{date_str}** รวม **{data_state['duration_days']} วัน**\n\nกรุณาพิมพ์เหตุผลในการลาครับ"
        ))
        return
        
    # STEP 6: Final Confirmation (confirm_leave)
    elif action == "confirm_leave" and current_step == "awaiting_confirmation":
        data_to_save = data_state
        line_user_id_submitting = user_id 
        
        save_successful = save_leave_to_firestore(line_user_id_submitting, data_to_save)
        clear_session_state(user_id) 
        
        if not save_successful:
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการบันทึกข้อมูล (Firestore) กรุณาลองใหม่อีกครั้งครับ"))
            
        image_path, image_url = generate_summary_image(data_to_save)
        
        summary_text = f"✅ บันทึกการลาเรียบร้อยแล้ว (ID: {data_to_save.get('doc_id', 'N/A')})\\n\\n**สถานะ: รอการอนุมัติ**"

        if image_path and image_url:
            # ส่งเป็น Image Map หรือ Image Message แทนการส่ง Text ธรรมดา
            # เนื่องจาก LineBot API ไม่รองรับ ImageMapAction ใน QuickReplyButton (ต้องใช้ ImageSendMessage)
            image_message = ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url 
            )
            line_bot_api.reply_message(reply_token, [
                TextSendMessage(text=summary_text),
                image_message
            ])
        else:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=summary_text))
        
        # 💡 NEW: แจ้งเตือน Admin ว่ามีรายการใหม่เข้ามา
        admin_alert_text = (
            "🔔 **แจ้งเตือน Admin: คำขอลาใหม่** 🔔\\n"
            f"ผู้ลา: {data_to_save.get('personnel_name', '-')}\\n"
            f"ประเภท: {data_to_save.get('leave_type', '-')}\\n"
            f"วันที่: {data_to_save.get('start_date', '-')} ถึง {data_to_save.get('end_date', '-')}\\n"
            "พิมพ์ `admin leave` เพื่อตรวจสอบและอนุมัติ"
        )
        line_bot_api.push_message(ADMIN_LINE_ID, TextSendMessage(text=admin_alert_text))
        
        return
