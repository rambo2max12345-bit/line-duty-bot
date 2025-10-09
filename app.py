# app.py - แก้ไขโดย Gemini: ใช้ Firestore เป็นฐานข้อมูลหลัก, เพิ่มระบบ Admin และฟังก์ชันอนุมัติการลา
import os
import json
import datetime
from flask import Flask, request, abort, url_for, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, PostbackEvent, TextMessage, TextSendMessage, TemplateSendMessage, 
    CarouselTemplate, CarouselColumn, PostbackAction, QuickReply, QuickReplyButton, 
    DatetimePickerAction, ImageSendMessage, FlexSendMessage
)
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore import FieldFilter
from PIL import Image, ImageDraw, ImageFont

# --- Configuration and Initialization ---

# Environment variables
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
FIREBASE_CREDENTIALS_JSON = os.getenv("FIREBASE_CREDENTIALS_JSON")

# 🌟 NEW: Admin Configuration 🌟
# ใช้ LINE User ID ของคุณที่ตรงกับ '466123' ในการเข้าถึงคำสั่ง admin
ADMIN_LINE_ID = "U" + "max466123" # โปรดแทนที่ 'U466123' ด้วย LINE User ID จริงของผู้ดูแล

# LINE API setup
line_bot_api = None
handler = None
if CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET:
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(CHANNEL_SECRET)
else:
    print("FATAL: LINE credentials not set.")
    abort(500)

# Firebase setup
db = None
if FIREBASE_CREDENTIALS_JSON:
    try:
        cred_dict = json.loads(FIREBASE_CREDENTIALS_JSON)
        cred = credentials.Certificate(cred_dict)
        initialize_app(cred)
        db = firestore.client()
        print("Firebase initialized successfully.")
    except Exception as e:
        print(f"FATAL: Error initializing Firebase: {e}")
else:
    print("FATAL: FIREBASE_CREDENTIALS_JSON not set.")
    abort(500)

# Flask app setup
app = Flask(__name__)

# Image serving path
IMAGE_DIR = "/tmp/line_bot_images"
os.makedirs(IMAGE_DIR, exist_ok=True)
FONT_PATH = "arial.ttf" # **โปรดตรวจสอบว่าฟอนต์นี้มีอยู่และรองรับภาษาไทย**

# Constants
PERSONNEL_COLLECTION = "personnel"
DUTY_COLLECTION = "duty_rotation"
LEAVE_COLLECTION = "line_duty_leave"
DEFAULT_LEAVE_HOURS = 8

# --- Utility Functions ---

def is_admin(user_id):
    """Checks if the user ID is the configured admin ID."""
    # Note: LINE User IDs typically start with 'U'
    return user_id == ADMIN_LINE_ID

def get_personnel_data():
    """Retrieves all personnel data from Firestore."""
    try:
        docs = db.collection(PERSONNEL_COLLECTION).stream()
        return [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"Error fetching personnel data: {e}")
        return []

def get_user_name(line_id):
    """Finds user name from line_id using Firestore."""
    personnel = get_personnel_data()
    for p in personnel:
        if p.get("line_id") == line_id:
            return p.get("name")
    return None

def get_duty_by_date(date_str):
    """Calculates duty assignment for a given date using Firestore data."""
    personnel = get_personnel_data()
    if not personnel:
        return None

    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    # Retrieve duty definitions from Firestore (assuming a fixed set of duties)
    duty_defs = []
    try:
        docs = db.collection(DUTY_COLLECTION).order_by("priority").stream()
        duty_defs = [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"Error fetching duty rotation data: {e}")
        return None

    if not duty_defs:
        return None

    # Sort personnel by duty_priority if available, otherwise use list order
    personnel.sort(key=lambda x: x.get("duty_priority", 999))
    num_personnel = len(personnel)

    # --- Duty Rotation Logic (Must Match Your Actual System) ---
    # Assuming a simple sequential rotation through personnel for each duty slot
    
    reference_date = datetime.date(2024, 1, 1) # Reference date for rotation cycle
    day_diff = (date_obj - reference_date).days
    
    duty_assignments = []
    
    for i, duty_info in enumerate(duty_defs):
        # Example logic: Rotate personnel based on day difference and duty index
        person_index = (day_diff + i) % num_personnel
        person = personnel[person_index]
        duty_assignments.append({
            "duty": duty_info.get("duty_name", "Duty N/A"), 
            "name": person.get("name", "Name N/A"), 
            "color": duty_info.get("color", "#000000")
        })
        
    return duty_assignments

# --- Firebase Functions ---

def save_leave_to_firestore(line_id, name, date_start, date_end, leave_type, hours):
    """Saves leave request to Firestore."""
    try:
        doc_ref = db.collection(LEAVE_COLLECTION).document()
        doc_ref.set({
            "line_id": line_id,
            "name": name,
            "date_start": date_start,
            "date_end": date_end,
            "leave_type": leave_type,
            "hours": hours,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "status": "Pending",
            "doc_id": doc_ref.id # Save ID for later approval
        })
        return True
    except Exception as e:
        print(f"Error saving leave to Firestore: {e}")
        return False
        
# --- Admin Handlers (New) ---

def handle_admin_command(event, text):
    """Handles commands exclusively for the admin."""
    command = text.lower().split()
    reply_token = event.reply_token

    if len(command) == 1 or command[1] == "help":
        help_text = (
            "🛠️ **Admin Commands**\n"
            "• `admin leave` : ดูรายการลาที่รอการอนุมัติ\n"
            "• **การจัดการข้อมูลกำลังพลและเวร (CRUD):**\n"
            "   *ต้องทำผ่าน Firebase Console โดยตรง ณ ตอนนี้*\n"
            "   (Collection: `personnel`, `duty_rotation`)"
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
    try:
        # 🌟 Use FieldFilter for better query performance 🌟
        docs = db.collection(LEAVE_COLLECTION).where(filter=FieldFilter("status", "==", "Pending")).stream()
        pending_leaves = [doc.to_dict() for doc in docs]
    except Exception as e:
        print(f"Error querying pending leaves: {e}")
        line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ เกิดข้อผิดพลาดในการดึงรายการลา"))
        return

    if not pending_leaves:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="✅ ไม่มีรายการลาที่รอการอนุมัติ"))
        return

    # Create Carousel Columns (LINE limits to 10 columns)
    columns = []
    for leave in pending_leaves[:10]:
        start = leave.get("date_start", "N/A")
        end = leave.get("date_end", "N/A")
        hours = leave.get("hours", "N/A")
        
        column = CarouselColumn(
            title=f"⏳ {leave.get('leave_type')}",
            text=f"{leave.get('name')}\n{start} ถึง {end} ({hours} ชม.)",
            actions=[
                PostbackAction(
                    label="✔️ อนุมัติ", 
                    data=f"action=approve_leave&doc_id={leave['doc_id']}"
                ),
                PostbackAction(
                    label="❌ ไม่อนุมัติ", 
                    data=f"action=reject_leave&doc_id={leave['doc_id']}"
                ),
            ]
        )
        columns.append(column)

    if columns:
        line_bot_api.reply_message(
            reply_token,
            TemplateSendMessage(
                alt_text=f"มี {len(pending_leaves)} รายการลาที่รออนุมัติ",
                template=CarouselTemplate(columns=columns)
            )
        )

# --- Image Generation Function (Unchanged) ---
# (Omitted for brevity, assuming it's the same as the previous version)

def create_duty_image(date_str, assignments):
    # ... Same Image Generation Logic as before ...
    # This function uses the FONT_PATH and assumes the duty/name/color data is passed correctly.
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None

    thai_months = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", 
                   "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    thai_days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]

    day_name = thai_days[date_obj.weekday()]
    month_name = thai_months[date_obj.month - 1]
    year_buddhist = date_obj.year + 543
    display_date = f"วัน{day_name} ที่ {date_obj.day} {month_name} {year_buddhist}"

    W, H = 600, 300
    img = Image.new('RGB', (W, H), color='white')
    d = ImageDraw.Draw(img)

    try:
        font_header = ImageFont.truetype(FONT_PATH, 30)
        font_body = ImageFont.truetype(FONT_PATH, 25)
    except IOError:
        font_header = ImageFont.load_default()
        font_body = ImageFont.load_default()

    header_text = f"บัญชีเวรประจำวันที่"
    d.text((W/2, 40), header_text, fill=(0, 0, 0), font=font_header, anchor="mm")
    d.text((W/2, 80), display_date, fill=(0, 0, 0), font=font_header, anchor="mm")
    
    y_start = 130
    line_height = 40
    
    for i, assignment in enumerate(assignments):
        duty_text = f"{assignment['duty']}:"
        name_text = assignment['name']
        color = assignment.get('color', '#000000')

        d.text((50, y_start + i * line_height), duty_text, fill=(0, 0, 0), font=font_body)
        d.text((W/2, y_start + i * line_height), name_text, fill=color, font=font_body)

    filename = f"duty_{date_str}.png"
    filepath = os.path.join(IMAGE_DIR, filename)
    img.save(filepath, "PNG")

    return filename

# --- LINE Messaging Handlers (Modified) ---

@app.route("/webhook", methods=["POST"])
def webhook():
    # ... Same Webhook Logic ...
    if not handler or not line_bot_api:
        abort(500)
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception:
        abort(500)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    reply_token = event.reply_token
    user_id = event.source.user_id

    # 🌟 NEW: Admin Check 🌟
    if is_admin(user_id) and text.lower().startswith("admin"):
        handle_admin_command(event, text)
        return

    # --- User Commands (Unchanged) ---
    if text in ["เวร", "เวรวันนี้"]:
        date_today = datetime.date.today().strftime("%Y-%m-%d")
        assignments = get_duty_by_date(date_today)
        send_duty_message(reply_token, date_today, assignments)
    elif text in ["ลา", "ขอลา"]:
        # Initiate leave request process
        send_leave_menu(reply_token)
    else:
        # Default reply
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(
                text="🤖 ยินดีต้อนรับ! คุณต้องการตรวจสอบเวรหรือแจ้งลา?\n\nพิมพ์ 'เวร' เพื่อดูเวรวันนี้\nพิมพ์ 'ลา' เพื่อแจ้งความประสงค์ขอลา",
                quick_reply=QuickReply(
                    items=[
                        QuickReplyButton(action=PostbackAction(label="เวรวันนี้", data="action=show_duty&date=today")),
                        QuickReplyButton(action=PostbackAction(label="แจ้งลา", data="action=select_leave_type")),
                    ]
                )
            )
        )
# ... send_duty_message, send_leave_menu functions (Unchanged) ...

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    params = {}
    try:
        for item in data.split('&'):
            key, value = item.split('=', 1)
            params[key] = value
    except ValueError:
        line_bot_api.reply_message(reply_token, TextSendMessage(text="ขออภัย ข้อมูลปุ่มไม่ถูกต้อง"))
        return

    action = params.get('action')

    # 🌟 NEW: Admin Approval Actions 🌟
    if action in ["approve_leave", "reject_leave"] and is_admin(user_id):
        doc_id = params.get('doc_id')
        status = "Approved" if action == "approve_leave" else "Rejected"
        
        try:
            doc_ref = db.collection(LEAVE_COLLECTION).document(doc_id)
            doc = doc_ref.get()
            if doc.exists:
                doc_data = doc.to_dict()
                doc_ref.update({"status": status, "reviewed_by": user_id, "review_timestamp": firestore.SERVER_TIMESTAMP})
                
                # Push message to the user who requested leave
                push_text = f"✅ คำขอลา{doc_data['leave_type']} ({doc_data['date_start']} ถึง {doc_data['date_end']}) ได้รับการ**{status}**แล้ว"
                line_bot_api.push_message(doc_data['line_id'], TextSendMessage(text=push_text))

                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"✅ อัปเดตสถานะของ {doc_data['name']} เป็น **{status}** และแจ้งผู้ลาแล้ว"))
                return
            else:
                line_bot_api.reply_message(reply_token, TextSendMessage(text="❌ ไม่พบรายการลาที่ต้องการอัปเดต"))
                return
        except Exception as e:
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"❌ ข้อผิดพลาดในการอัปเดต: {e}"))
            return
            
    # --- User Postback Actions (Unchanged) ---
    # ... show_duty, select_leave_type, select_date, select_end_date, confirm_leave, submit_leave, cancel_leave ...
    
    # [Rest of Postback logic remains the same as before for users]
    # To keep the file brief, the rest of the postback logic is assumed to be copied here.
    # ...

# --- Image Serving Endpoint (Unchanged) ---
@app.route("/images/<filename>")
def serve_image(filename):
    # ... Same Image Serving Logic ...
    filepath = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(filepath):
        return send_file(filepath, mimetype='image/png')
    abort(404)

# --- Run Application ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

