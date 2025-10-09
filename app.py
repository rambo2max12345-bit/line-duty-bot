# app.py - Updated with REST CRUD API endpoints for personnel, duties, leaves, duty-logs, and sessions
import os
import json
import uuid
from datetime import datetime, timedelta, date

from flask import Flask, request, abort, url_for, send_from_directory, jsonify, make_response
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, PostbackEvent, TextMessage, TextSendMessage, TemplateSendMessage,
    CarouselTemplate, CarouselColumn, PostbackAction, QuickReply, QuickReplyButton,
    DatetimePickerAction, ImageSendMessage, MessageAction
)

import firebase_admin
from firebase_admin import credentials, initialize_app, firestore

# Optional image libs
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

# --- Configuration and Initialization ---
app = Flask(__name__)

# Environment variables (set on Render)
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")

# Admin (can be set to comma-separated list)
ADMIN_LINE_ID = os.getenv("ADMIN_LINE_ID", "max466123")
# Admin API key for REST admin actions (set this in ENV)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

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

        # Avoid double initialize across forked workers
        if not firebase_admin._apps:
            initialize_app(cred)

        db = firestore.client()
        app.logger.info("Firebase connected successfully.")
    else:
        app.logger.warning("FIREBASE_CREDENTIALS_JSON not set. Firebase functions will fail.")
except Exception as e:
    app.logger.error(f"FATAL: Error initializing Firebase: {e}")

# Image setup (Requires Pillow and a Thai font)
IMAGE_DIR = "/tmp/line_bot_images"
os.makedirs(IMAGE_DIR, exist_ok=True)

FONT_FILENAME = os.getenv("FONT_FILENAME", "Sarabun-Regular.ttf")
FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)
try:
    if ImageFont and FONT_PATH:
        try:
            ImageFont.truetype(FONT_PATH, 12)
            app.logger.info(f"Custom font loaded successfully from {FONT_PATH}.")
        except Exception:
            FONT_PATH = None
            app.logger.warning(f"Custom font file '{FONT_FILENAME}' not found. Using default font.")
except Exception:
    FONT_PATH = None

# Constants
PERSONNEL_COLLECTION = "personnel"
DUTY_COLLECTION = "duty_rotation"
LEAVE_COLLECTION = "line_duty_leave"
SESSION_COLLECTION = "user_sessions"
DUTY_LOGS_COLLECTION = "duty_logs"
LEAVE_TYPES = ["ลาพัก", "ลากิจ", "ลาป่วย", "ราชการ"]

# Status constants (use consistent values for Firestore)
STATUS_PENDING = "Pending"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"

# --- UTILITY & DATA FUNCTIONS (State Management) ---
def get_session_state(user_id):
    if not db:
        return None
    try:
        doc = db.collection(SESSION_COLLECTION).document(user_id).get()
        return doc.to_dict() if doc.exists else None
    except Exception as e:
        app.logger.error(f"Error fetching session for {user_id}: {e}")
        return None

def save_session_state(user_id, step, data):
    if not db:
        return False
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
    if not db:
        return
    try:
        db.collection(SESSION_COLLECTION).document(user_id).delete()
    except Exception as e:
        app.logger.error(f"Error clearing session for {user_id}: {e}")

# --- UTILITY & DATA FUNCTIONS (General) ---
def is_admin(user_id):
    if not user_id:
        return False
    admins = [a.strip() for a in ADMIN_LINE_ID.split(",") if a.strip()]
    return user_id in admins

def _get_font(size):
    if ImageFont and FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            app.logger.warning(f"Error loading TrueType font from {FONT_PATH}. Using default font.")
    if ImageFont:
        try:
            return ImageFont.load_default()
        except Exception:
            return None
    return None

def get_personnel_data():
    if not db:
        return []
    try:
        docs = db.collection(PERSONNEL_COLLECTION).stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        app.logger.error(f"Error fetching personnel data: {e}")
        return []

def get_personnel_names():
    return [p.get('name') for p in get_personnel_data() if p.get('name')]

def get_leaves_on_date(date_str):
    """Retrieves approved leave data that covers the given date."""
    if not db:
        return []
    try:
        target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        docs = db.collection(LEAVE_COLLECTION).where("status", "==", STATUS_APPROVED).stream()
        all_approved_leaves = [doc.to_dict() for doc in docs]
        leaves_on_date = []
        for leave in all_approved_leaves:
            try:
                start = datetime.strptime(leave.get('start_date'), '%Y-%m-%d').date()
                end = datetime.strptime(leave.get('end_date'), '%Y-%m-%d').date()
                if start <= target_date <= end:
                    leaves_on_date.append(leave)
            except Exception:
                continue
        return leaves_on_date
    except Exception as e:
        app.logger.error(f"Error fetching leaves on date {date_str}: {e}")
        return []

def get_duty_by_date(date_str):
    if not db:
        return []
    personnel = get_personnel_data()
    if not personnel:
        return []

    # Filter out personnel who are on approved leave this date
    leave_list = get_leaves_on_date(date_str)
    leave_map = {leave['personnel_name']: leave['leave_type'] for leave in leave_list}

    available_personnel = [p for p in personnel if p.get('name') not in leave_map]
    if not available_personnel:
        # Return leaves only if everyone is on leave
        assignments = []
        for name, leave_type in leave_map.items():
            assignments.append({
                "duty": f"ลา ({leave_type})",
                "name": name,
                "color": "#FF0000",
                "status": "ลา"
            })
        return assignments

    # Sort by duty_priority
    available_personnel.sort(key=lambda x: x.get("duty_priority", 999))
    num_personnel = len(available_personnel)

    # Fetch duty definitions
    duty_defs = []
    try:
        docs = db.collection(DUTY_COLLECTION).order_by("priority").stream()
        duty_defs = [doc.to_dict() for doc in docs]
    except Exception as e:
        app.logger.error(f"Error fetching duty rotation data: {e}")
        return []

    if not duty_defs:
        return []

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return []

    reference_date = date(2024, 1, 1)
    day_diff = (date_obj - reference_date).days

    duty_assignments = []
    for i, duty_info in enumerate(duty_defs):
        person_index = (day_diff + i) % num_personnel
        person = available_personnel[person_index]
        duty_assignments.append({
            "duty": duty_info.get("duty_name", "Duty N/A"),
            "name": person.get("name", "Name N/A"),
            "color": duty_info.get("color", "#000000"),
            "status": "ปฏิบัติงาน"
        })

    # Add leave entries
    for name, leave_type in leave_map.items():
        duty_assignments.append({
            "duty": f"ลา ({leave_type})",
            "name": name,
            "color": "#FF0000",
            "status": "ลา"
        })

    return duty_assignments

def save_leave_to_firestore(line_id, data):
    if not db:
        return False
    try:
        doc_ref = db.collection(LEAVE_COLLECTION).document()
        data.update({
            "line_id": line_id,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": STATUS_PENDING,
            "doc_id": doc_ref.id,
            "submission_date": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        doc_ref.set(data)
        return True
    except Exception as e:
        app.logger.error(f"Error saving leave to Firestore: {e}")
        return False

def get_duty_log_for_today(name, log_type):
    if not db:
        return None
    today_str = datetime.now().strftime('%Y-%m-%d')
    try:
        query = db.collection(DUTY_LOGS_COLLECTION) \
            .where("name", "==", name) \
            .where("date", "==", today_str) \
            .where("log_type", "==", log_type) \
            .limit(1).stream()
        docs = list(query)
        return docs[0].to_dict() if docs else None
    except Exception as e:
        app.logger.error(f"Error checking duty log: {e}")
        return None

def log_duty_action(user_id, name, log_type):
    if not db:
        return False, "❌ Backend (Firestore) ไม่พร้อมใช้งาน"
    today_str = datetime.now().strftime('%Y-%m-%d')
    time_str = datetime.now().strftime('%H:%M:%S')

    existing_log = get_duty_log_for_today(name, log_type)
    if existing_log:
        return False, f"คุณได้ลงเวลา{log_type}แล้วเมื่อ {existing_log.get('time', 'N/A')} วันนี้"

    assignments = get_duty_by_date(today_str)
    on_duty_names = [a['name'] for a in assignments if a.get('status') == 'ปฏิบัติงาน']

    if name not in on_duty_names:
        return False, f"⚠️ คุณ {name} ไม่ได้มีเวรประจำวันนี้"

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
    if Image is None:
        return None, None
    try:
        filename = f"leave_summary_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(IMAGE_DIR, filename)

        width, height = 650, 480
        img = Image.new('RGB', (width, height), color='#F0F4F8')
        d = ImageDraw.Draw(img)

        font_title = _get_font(36) or ImageFont.load_default()
        font_header = _get_font(20) or ImageFont.load_default()
        font_body = _get_font(18) or ImageFont.load_default()

        d.rectangle((20, 20, width - 20, height - 20), fill='#FFFFFF', outline='#007BFF', width=3)
        title_text = "ใบแจ้งลาอิเล็กทรอนิกส์"
        try:
            d.text((width/2, 40), title_text, fill=(25, 25, 112), font=font_title, anchor="mt")
        except Exception:
            # Older PIL may not support anchor
            tw, th = d.textsize(title_text, font=font_title)
            d.text(((width - tw) / 2, 40), title_text, fill=(25, 25, 112), font=font_title)

        lines = [
            ("ประเภทการลา:", data.get('leave_type', '-')),
            ("ชื่อผู้ลา:", data.get('personnel_name', '-')),
            ("วันที่เริ่มต้น:", data.get('start_date', '-')),
            ("วันที่สิ้นสุด:", data.get('end_date', '-')),
            ("รวมระยะเวลา:", f"{data.get('duration_days', '-')} วัน"),
            ("เหตุผล:", data.get('reason', '-')),
            ("สถานะ:", "รอการอนุมัติ (Pending)")
        ]

        y_offset = 110
        line_height = 36
        for key, value in lines:
            d.text((50, y_offset), key, fill=(50, 50, 50), font=font_header)
            try:
                d.text((300, y_offset), str(value), fill=(0, 0, 0), font=font_body)
            except Exception:
                d.text((300, y_offset), str(value), fill=(0, 0, 0))
            y_offset += line_height

        img.save(filepath)

        # Build external URL for the saved image (must ensure Render/public routing or external url is enabled)
        image_url = url_for('serve_image', filename=filename, _external=True)
        return filepath, image_url
    except Exception as e:
        app.logger.error(f"Image generation failed: {e}")
        return None, None

def build_duty_summary_text(date_str, assignments):
    if not assignments:
        return f"ไม่พบข้อมูลเวรสำหรับวันที่ {date_str}"
    summary_lines = [f"🗓️ เวรประจำวันที่ {date_str}"]
    for item in assignments:
        if item.get('status') == 'ปฏิบัติงาน':
            log_in = get_duty_log_for_today(item['name'], 'checkin')
            log_out = get_duty_log_for_today(item['name'], 'checkout')
            label = ""
            if log_in and log_out:
                label = f"💯 ครบ ({log_in.get('time')}-{log_out.get('time')})"
            elif log_in and not log_out:
                label = f"⏳ ปฏิบัติงาน ({log_in.get('time')})"
            elif not log_in and log_out:
                label = f"❌ ออก ({log_out.get('time')})"
            else:
                label = "❗ ยังไม่เข้า"
            summary_lines.append(f"▶️ {item.get('duty')}: {item.get('name')} [{label}]")
        else:
            summary_lines.append(f"🌴 {item.get('duty')}: {item.get('name')}")
    return "\n".join(summary_lines)

# --- ADMIN HANDLERS (LINE) ---
def handle_admin_command(event, text):
    command = text.lower().split()
    reply_token = event.reply_token

    if len(command) == 1 or command[1] == "help":
        help_text = (
            "🛠️ Admin Commands:\n"
            "• admin leave : ดูรายการลาที่รอการอนุมัติ\n"
            "• (จัดการข้อมูลกำลังพลและเวรผ่าน Firebase Console)"
        )
        line_bot_api.reply_message(reply_token, TextSendMessage(text=help_text))
        return
    elif command[1] == "leave":
        send_pending_leaves(reply_token)
        return
    else:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="ไม่พบคำสั่ง Admin นี้ พิมพ์ `admin help`"))

def send_pending_leaves(reply_token):
    if not db:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ Firebase ไม่พร้อมใช้งาน"))
        return
    try:
        docs = db.collection(LEAVE_COLLECTION).where("status", "==", STATUS_PENDING).stream()
        pending_leaves = [doc.to_dict() for doc in docs]
    except Exception as e:
        app.logger.error(f"Error querying pending leaves: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ เกิดข้อผิดพลาดในการดึงรายการลา"))
        return

    if not pending_leaves:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="✅ ไม่มีรายการลาที่รอการอนุมัติ"))
        return

    columns = []
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

# --- FLASK ROUTES (LINE handling) ---
@app.route("/images/<filename>")
def serve_image(filename):
    try:
        return send_from_directory(IMAGE_DIR, filename)
    except Exception as e:
        app.logger.error(f"Error serving image {filename}: {e}")
        abort(404)

@app.route("/webhook", methods=['POST'])
def webhook():
    if not handler or not line_bot_api:
        app.logger.error("Service not ready (LINE/Firebase). Check environment variables.")
        return "Service Not Ready", 503

    signature = request.headers.get('X-Line-Signature')
    if not signature:
        app.logger.error("Missing X-Line-Signature header.")
        abort(400)

    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature received.")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error handling webhook: {e}")
        # Return OK to avoid excessive retries from LINE
        return 'OK'

    return 'OK'

# --- MESSAGE & POSTBACK HANDLERS (LINE) ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = (event.message.text or "").strip()
    reply_token = event.reply_token
    user_id = getattr(event.source, "user_id", None)

    if user_id is None:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="บอทยังไม่รองรับการใช้งานจาก group/room โปรดติดต่อเป็น 1:1 กับบอท"))
        return

    # Admin
    if is_admin(user_id) and text.lower().startswith("admin"):
        handle_admin_command(event, text)
        return

    # Start leave flow
    if text in ["ลา", "ขอลา", "#แจ้งลา"]:
        clear_session_state(user_id)
        save_session_state(user_id, "awaiting_leave_type", {})

        leave_buttons = [QuickReplyButton(action=MessageAction(label=lt, text=lt)) for lt in LEAVE_TYPES]
        leave_buttons.append(QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก")))

        reply_msg = TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=QuickReply(items=leave_buttons))
        line_bot_api.reply_message(reply_token, reply_msg)
        return

    # Duty summary
    elif text in ["เวร", "เวรวันนี้", "#เวร"]:
        date_today = datetime.now().strftime("%Y-%m-%d")
        assignments = get_duty_by_date(date_today)
        duty_text = build_duty_summary_text(date_today, assignments)
        line_bot_api.reply_message(reply_token, TextSendMessage(text=duty_text))
        return

    elif text == "#ยกเลิก":
        clear_session_state(user_id)
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ ยกเลิกการทำรายการเรียบร้อยแล้วครับ"))
        return

    # Check-in
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

    # Check-out
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

    # State-driven flow
    session_state = get_session_state(user_id)
    if session_state:
        current_step = session_state.get('step')
        data_state = session_state.get('data') or {}
        personnel_names = get_personnel_names()

        if current_step == "awaiting_leave_type" and text in LEAVE_TYPES:
            data_state['leave_type'] = text
            save_session_state(user_id, "awaiting_start_date", data_state)
            quick_reply_items = [
                QuickReplyButton(action=DatetimePickerAction(label="🗓️ เลือกวันเริ่มต้น", data="set_start_date", mode="date", initial=datetime.now().strftime('%Y-%m-%d'))),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ]
            line_bot_api.reply_message(reply_token, TextSendMessage(
                text=f"ประเภทการลา: {text}\nกรุณาเลือกวันเริ่มต้นการลาครับ",
                quick_reply=QuickReply(items=quick_reply_items)
            ))
            return

        elif current_step == "awaiting_reason":
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
            data_state['personnel_name'] = text
            save_session_state(user_id, "awaiting_confirmation", data_state)

            summary_text = (
                "สรุปรายการแจ้งลา:\n"
                f"ประเภท: {data_state.get('leave_type', '-')}\n"
                f"ชื่อผู้ลา: {data_state.get('personnel_name', '-')}\n"
                f"เริ่มต้น: {data_state.get('start_date', '-')}\n"
                f"สิ้นสุด: {data_state.get('end_date', '-')}\n"
                f"รวม: {data_state.get('duration_days', '-') } วัน\n"
                f"เหตุผล: {data_state.get('reason', '-')}"
            )
            confirm_buttons = [
                QuickReplyButton(action=PostbackAction(label="✅ ยืนยันการแจ้งลา", data="action=confirm_leave")),
                QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
            ]
            line_bot_api.reply_message(reply_token, TextSendMessage(text=summary_text, quick_reply=QuickReply(items=confirm_buttons)))
            return

        elif current_step == "awaiting_checkin_name" and text in personnel_names:
            success, message = log_duty_action(user_id, text, 'checkin')
            clear_session_state(user_id)
            date_today = datetime.now().strftime("%Y-%m-%d")
            assignments = get_duty_by_date(date_today)
            duty_text = build_duty_summary_text(date_today, assignments)
            line_bot_api.reply_message(reply_token, [TextSendMessage(text=message), TextSendMessage(text=duty_text)])
            return

        elif current_step == "awaiting_checkout_name" and text in personnel_names:
            success, message = log_duty_action(user_id, text, 'checkout')
            clear_session_state(user_id)
            date_today = datetime.now().strftime("%Y-%m-%d")
            assignments = get_duty_by_date(date_today)
            duty_text = build_duty_summary_text(date_today, assignments)
            line_bot_api.reply_message(reply_token, [TextSendMessage(text=message), TextSendMessage(text=duty_text)])
            return

        elif current_step.startswith("awaiting"):
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🤖 ขณะนี้คุณกำลังอยู่ในขั้นตอน '{current_step.replace('awaiting_', '')}' กรุณาดำเนินการต่อ หรือพิมพ์ #ยกเลิก ครับ"))
            return

    # Default menu
    else:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(
                text="🤖 เมนูหลัก\nคุณต้องการทำรายการใดครับ?",
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

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data or ""
    reply_token = event.reply_token
    user_id = getattr(event.source, "user_id", None)

    # Parse postback string robustly (support both key=val pairs and single token)
    params = {}
    try:
        for item in data.split('&'):
            if '=' in item:
                key, value = item.split('=', 1)
            elif item:
                # treat plain token as action
                key, value = "action", item
            else:
                continue
            params[key] = value
    except Exception as e:
        app.logger.error(f"Error parsing postback data: {e}")
        return line_bot_api.reply_message(reply_token, TextSendMessage(text="ขออภัย ข้อมูลปุ่มไม่ถูกต้อง"))

    action = params.get('action')
    doc_id = params.get('doc_id')

    # Admin approval
    if action in ["approve_leave", "reject_leave"] and is_admin(user_id):
        status = STATUS_APPROVED if action == "approve_leave" else STATUS_REJECTED
        try:
            doc_ref = db.collection(LEAVE_COLLECTION).document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                doc_data = doc.to_dict()
                doc_ref.update({"status": status, "reviewed_by": user_id, "review_timestamp": firestore.SERVER_TIMESTAMP})
                push_text = f"✅ คำขอลา {doc_data.get('leave_type','')} ของ {doc_data.get('personnel_name','N/A')} (วันที่ {doc_data.get('start_date','N/A')}) ได้รับการ {status}"
                recipient = doc_data.get('line_id') or user_id
                try:
                    line_bot_api.push_message(recipient, TextSendMessage(text=push_text))
                except Exception as e:
                    app.logger.error(f"Failed to push approval notification: {e}")
                return line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ อัปเดตสถานะของ {doc_data.get('personnel_name','N/A')} เป็น {status}"))
            else:
                return line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ ไม่พบรายการลาที่ต้องการอัปเดต"))
        except Exception as e:
            app.logger.error(f"Error in Admin Approval: {e}")
            return line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ ข้อผิดพลาดในการอัปเดต: {e}"))

    # Date param (for DatetimePicker)
    date_str = None
    try:
        if event.postback.params and 'date' in event.postback.params:
            date_str = event.postback.params.get('date')
    except Exception:
        date_str = None

    session_state = get_session_state(user_id)
    if not session_state:
        return line_bot_api.reply_message(reply_token, TextSendMessage(text="🤖 กรุณาพิมพ์ #แจ้งลา เพื่อเริ่มต้นการทำรายการใหม่ครับ"))

    current_step = session_state.get('step')
    data_state = session_state.get('data') or {}

    # Start date selected
    if action == "set_start_date" and current_step == "awaiting_start_date" and date_str:
        data_state['start_date'] = date_str
        save_session_state(user_id, "awaiting_end_date", data_state)

        quick_reply_items = [
            QuickReplyButton(action=DatetimePickerAction(label="🗓️ เลือกวันสิ้นสุด", data="set_end_date", mode="date", initial=date_str)),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ]
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=f"วันเริ่มต้น: {date_str}\nกรุณาเลือกวันสิ้นสุดการลาครับ",
            quick_reply=QuickReply(items=quick_reply_items)
        ))
        return

    # End date selected
    if action == "set_end_date" and current_step == "awaiting_end_date" and date_str:
        start_date_str = data_state.get('start_date')
        if not start_date_str:
            clear_session_state(user_id)
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาด ไม่พบวันเริ่มต้น กรุณาพิมพ์ #แจ้งลา ใหม่ครับ"))
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except Exception:
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ รูปแบบวันที่ไม่ถูกต้อง กรุณาลองใหม่"))

        if end_date < start_date:
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น กรุณาเลือกใหม่ครับ"))

        data_state['end_date'] = date_str
        data_state['duration_days'] = (end_date - start_date).days + 1
        save_session_state(user_id, "awaiting_reason", data_state)
        line_bot_api.reply_message(reply_token, TextSendMessage(
            text=f"🗓️ ระยะเวลาลา {start_date_str} ถึง {date_str} รวม {data_state['duration_days']} วัน\n\nกรุณาพิมพ์เหตุผลในการลาครับ"
        ))
        return

    # Final confirmation
    if action == "confirm_leave" and current_step == "awaiting_confirmation":
        data_to_save = data_state
        line_user_id_submitting = user_id
        save_successful = save_leave_to_firestore(line_user_id_submitting, data_to_save)
        clear_session_state(user_id)
        if not save_successful:
            return line_bot_api.reply_message(reply_token, TextSendMessage(text="⚠️ เกิดข้อผิดพลาดในการบันทึกข้อมูล (Firestore) กรุณาลองใหม่อีกครั้งครับ"))

        image_path, image_url = generate_summary_image(data_to_save)
        summary_text = f"✅ บันทึกการลาเรียบร้อยแล้ว (ID: {data_to_save.get('doc_id', 'N/A')})\n\nสถานะ: รอการอนุมัติ"

        messages = [TextSendMessage(text=summary_text)]
        if image_path and image_url:
            messages.append(ImageSendMessage(original_content_url=image_url, preview_image_url=image_url))
        line_bot_api.reply_message(reply_token, messages)

        admin_alert_text = (
            "🔔 แจ้งเตือน Admin: คำขอลาใหม่\n"
            f"ผู้ลา: {data_to_save.get('personnel_name', '-')}\n"
            f"ประเภท: {data_to_save.get('leave_type', '-')}\n"
            f"วันที่: {data_to_save.get('start_date', '-')} ถึง {data_to_save.get('end_date', '-')}\n"
            "พิมพ์ `admin leave` เพื่อตรวจสอบและอนุมัติ"
        )
        try:
            # Notify admins (comma-separated)
            for adm in [a.strip() for a in ADMIN_LINE_ID.split(",") if a.strip()]:
                line_bot_api.push_message(adm, TextSendMessage(text=admin_alert_text))
        except Exception as e:
            app.logger.error(f"Failed to notify admin: {e}")

        return

    # Fallback
    line_bot_api.reply_message(reply_token, TextSendMessage(text="ขออภัย ไม่สามารถประมวลผลคำสั่งนี้ได้"))

# -----------------------------
# REST CRUD API Endpoints (/api)
# -----------------------------
def admin_required():
    """Simple admin API key check. Expect header: Authorization: Bearer <ADMIN_API_KEY>"""
    auth_header = request.headers.get("Authorization", "")
    if not ADMIN_API_KEY:
        return False, "ADMIN_API_KEY not configured on server"
    if not auth_header.startswith("Bearer "):
        return False, "Missing Bearer token in Authorization header"
    token = auth_header.split(" ", 1)[1].strip()
    if token != ADMIN_API_KEY:
        return False, "Invalid API key"
    return True, ""

def _doc_to_dict(doc):
    d = doc.to_dict() if doc.exists else None
    if d is None:
        return None
    # ensure doc_id present
    d['doc_id'] = d.get('doc_id') or doc.id
    return d

# Personnel CRUD
@app.route("/api/personnel", methods=["GET"])
def api_get_personnel():
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        docs = db.collection(PERSONNEL_COLLECTION).stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            data['doc_id'] = data.get('doc_id') or doc.id
            items.append(data)
        return jsonify({"success": True, "data": items})
    except Exception as e:
        app.logger.error(f"API GET personnel error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/personnel", methods=["POST"])
def api_create_personnel():
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    payload = request.get_json() or {}
    try:
        doc_ref = db.collection(PERSONNEL_COLLECTION).document()
        payload['doc_id'] = doc_ref.id
        doc_ref.set(payload)
        return make_response(jsonify({"success": True, "data": payload}), 201)
    except Exception as e:
        app.logger.error(f"API CREATE personnel error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/personnel/<doc_id>", methods=["GET"])
def api_get_personnel_item(doc_id):
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        doc = db.collection(PERSONNEL_COLLECTION).document(doc_id).get()
        if not doc.exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        data = _doc_to_dict(doc)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        app.logger.error(f"API GET personnel/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/personnel/<doc_id>", methods=["PUT"])
def api_update_personnel(doc_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    payload = request.get_json() or {}
    try:
        doc_ref = db.collection(PERSONNEL_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        doc_ref.update(payload)
        doc = doc_ref.get()
        return jsonify({"success": True, "data": _doc_to_dict(doc)})
    except Exception as e:
        app.logger.error(f"API UPDATE personnel/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/personnel/<doc_id>", methods=["DELETE"])
def api_delete_personnel(doc_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    try:
        doc_ref = db.collection(PERSONNEL_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        doc_ref.delete()
        return jsonify({"success": True, "message": "Deleted"})
    except Exception as e:
        app.logger.error(f"API DELETE personnel/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

# Duties CRUD (duty_rotation)
@app.route("/api/duties", methods=["GET"])
def api_get_duties():
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        docs = db.collection(DUTY_COLLECTION).order_by("priority").stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            data['doc_id'] = data.get('doc_id') or doc.id
            items.append(data)
        return jsonify({"success": True, "data": items})
    except Exception as e:
        app.logger.error(f"API GET duties error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/duties", methods=["POST"])
def api_create_duty():
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    payload = request.get_json() or {}
    try:
        doc_ref = db.collection(DUTY_COLLECTION).document()
        payload['doc_id'] = doc_ref.id
        doc_ref.set(payload)
        return make_response(jsonify({"success": True, "data": payload}), 201)
    except Exception as e:
        app.logger.error(f"API CREATE duty error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/duties/<doc_id>", methods=["PUT"])
def api_update_duty(doc_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    payload = request.get_json() or {}
    try:
        doc_ref = db.collection(DUTY_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        doc_ref.update(payload)
        return jsonify({"success": True, "data": _doc_to_dict(doc_ref.get())})
    except Exception as e:
        app.logger.error(f"API UPDATE duty/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/duties/<doc_id>", methods=["DELETE"])
def api_delete_duty(doc_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    try:
        doc_ref = db.collection(DUTY_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        doc_ref.delete()
        return jsonify({"success": True, "message": "Deleted"})
    except Exception as e:
        app.logger.error(f"API DELETE duty/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

# Leaves CRUD
@app.route("/api/leaves", methods=["GET"])
def api_get_leaves():
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        q = db.collection(LEAVE_COLLECTION)
        # optional filters
        status = request.args.get("status")
        line_id = request.args.get("line_id")
        personnel_name = request.args.get("personnel_name")
        # note: for date filtering we retrieve and filter in Python (consistent with earlier approach)
        if status:
            q = q.where("status", "==", status)
        if line_id:
            q = q.where("line_id", "==", line_id)
        if personnel_name:
            q = q.where("personnel_name", "==", personnel_name)
        docs = q.stream()
        items = []
        date_filter = request.args.get("date")  # YYYY-MM-DD
        for doc in docs:
            data = doc.to_dict()
            data['doc_id'] = data.get('doc_id') or doc.id
            if date_filter:
                try:
                    start = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
                    end = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
                    target = datetime.strptime(date_filter, '%Y-%m-%d').date()
                    if not (start <= target <= end):
                        continue
                except Exception:
                    continue
            items.append(data)
        return jsonify({"success": True, "data": items})
    except Exception as e:
        app.logger.error(f"API GET leaves error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/leaves", methods=["POST"])
def api_create_leave():
    payload = request.get_json() or {}
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        # normalize status
        payload['status'] = payload.get('status', STATUS_PENDING)
        doc_ref = db.collection(LEAVE_COLLECTION).document()
        payload['doc_id'] = doc_ref.id
        payload['submission_date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        doc_ref.set(payload)
        return make_response(jsonify({"success": True, "data": payload}), 201)
    except Exception as e:
        app.logger.error(f"API CREATE leave error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/leaves/<doc_id>", methods=["GET"])
def api_get_leave(doc_id):
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        doc = db.collection(LEAVE_COLLECTION).document(doc_id).get()
        if not doc.exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        return jsonify({"success": True, "data": _doc_to_dict(doc)})
    except Exception as e:
        app.logger.error(f"API GET leave/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/leaves/<doc_id>", methods=["PUT"])
def api_update_leave(doc_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    payload = request.get_json() or {}
    try:
        doc_ref = db.collection(LEAVE_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        doc_ref.update(payload)
        return jsonify({"success": True, "data": _doc_to_dict(doc_ref.get())})
    except Exception as e:
        app.logger.error(f"API UPDATE leave/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/leaves/<doc_id>", methods=["DELETE"])
def api_delete_leave(doc_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    try:
        doc_ref = db.collection(LEAVE_COLLECTION).document(doc_id)
        if not doc_ref.get().exists:
            return make_response(jsonify({"success": False, "error": "Not found"}), 404)
        doc_ref.delete()
        return jsonify({"success": True, "message": "Deleted"})
    except Exception as e:
        app.logger.error(f"API DELETE leave/{doc_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

# Duty logs (read and create)
@app.route("/api/duty-logs", methods=["GET"])
def api_get_duty_logs():
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        q = db.collection(DUTY_LOGS_COLLECTION)
        name = request.args.get("name")
        date = request.args.get("date")
        log_type = request.args.get("log_type")
        if name:
            q = q.where("name", "==", name)
        if date:
            q = q.where("date", "==", date)
        if log_type:
            q = q.where("log_type", "==", log_type)
        docs = q.order_by("timestamp", direction=firestore.Query.DESCENDING).stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            data['doc_id'] = doc.id
            items.append(data)
        return jsonify({"success": True, "data": items})
    except Exception as e:
        app.logger.error(f"API GET duty-logs error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/duty-logs", methods=["POST"])
def api_create_duty_log():
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    payload = request.get_json() or {}
    required = ["name", "log_type"]
    for r in required:
        if r not in payload:
            return make_response(jsonify({"success": False, "error": f"Missing field: {r}"}), 400)
    try:
        payload['date'] = payload.get('date', datetime.now().strftime('%Y-%m-%d'))
        payload['time'] = payload.get('time', datetime.now().strftime('%H:%M:%S'))
        payload['timestamp'] = firestore.SERVER_TIMESTAMP
        doc_ref = db.collection(DUTY_LOGS_COLLECTION).document()
        doc_ref.set(payload)
        payload['doc_id'] = doc_ref.id
        return make_response(jsonify({"success": True, "data": payload}), 201)
    except Exception as e:
        app.logger.error(f"API CREATE duty-log error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

# Sessions (list and delete)
@app.route("/api/sessions", methods=["GET"])
def api_get_sessions():
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        docs = db.collection(SESSION_COLLECTION).stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            data['doc_id'] = data.get('doc_id') or doc.id
            items.append(data)
        return jsonify({"success": True, "data": items})
    except Exception as e:
        app.logger.error(f"API GET sessions error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)

@app.route("/api/sessions/<user_id>", methods=["DELETE"])
def api_delete_session(user_id):
    ok, msg = admin_required()
    if not ok:
        return make_response(jsonify({"success": False, "error": msg}), 401)
    if not db:
        return make_response(jsonify({"success": False, "error": "Firestore not initialized"}), 503)
    try:
        db.collection(SESSION_COLLECTION).document(user_id).delete()
        return jsonify({"success": True, "message": "Session deleted"})
    except Exception as e:
        app.logger.error(f"API DELETE session/{user_id} error: {e}")
        return make_response(jsonify({"success": False, "error": str(e)}), 500)
