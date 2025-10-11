# app.py - LINE Duty Bot with REST CRUD endpoints (ready-to-run)
import os
import json
import uuid
from datetime import datetime, date

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

# Environment variables (set these before running)
CHANNEL_ACCESS_TOKEN = os.getenv("1CnVa/zE6C8/TzIzHo2zfGEGbvUIRmUUsVYOydz6tq3we8IB/wORSikLPcySu3CxAwTYGoGUjmSLMlCqKnqwMm5JVvPO99Lupsn+p4rQ7orQkd/+cA1uArroKQH1haQHNIZwck+QlkkIpPujWModBQdB04t89/1O/w1cDnyilFU=
")
CHANNEL_SECRET = os.getenv("b3985ff63851dc0c8505e43ac7d6a926")
FIREBASE_CREDENTIALS_JSON = os.getenv("{"type": "service_account", "project_id": "...", "private_key_id": "...", "private_key": "...", "client_email": "...", "client_id": "...", "auth_uri": "...", "token_uri": "...", "auth_provider_x509_cert_url": "...", "client_x509_cert_url": "..."}")
ADMIN_LINE_ID = os.getenv("ADMIN_LINE_ID", "max466123")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")

# LINE API setup
line_bot_api = None
handler = None
if CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET:
    line_bot_api = LineBotApi(8Qa3lq+KjkF68P1W6xAkkuRyoXpz9YyuQI2nOKJRu/ndsvfGLZIft6ltdgYV8vMEbBkz5AWzYoF+CaS7u0OShmuZvo5Yufb6+Xvr4gBti4Gc4cp45MCnyD0cte94vZyyEhLKC3WJKvd9usUXqCwrOgdB04t89/1O/w1cDnyilFU=
)
    handler = WebhookHandler(1d0c51790d0bff2b98dbb98dc8f72663)
else:
    app.logger.warning("LINE credentials not set. LINE features will be disabled until configured.")

# Firebase setup
db = None
try:
    if FIREBASE_CREDENTIALS_JSON:
        cred_dict = json.loads({"type": "service_account", "project_id": "...", "private_key_id": "...", "private_key": "...", "client_email": "...", "client_id": "...", "auth_uri": "...", "token_uri": "...", "auth_provider_x509_cert_url": "...", "client_x509_cert_url": "..."})
        cred = credentials.Certificate(cred_dict)
        # avoid re-initialize
        if not firebase_admin._apps:
            initialize_app(cred)
        db = firestore.client()
        app.logger.info("Firebase connected successfully.")
    else:
        app.logger.warning("FIREBASE_CREDENTIALS_JSON not set. Firestore will be disabled.")
except Exception as e:
    app.logger.error(f"Error initializing Firebase: {e}")

# Image directory
IMAGE_DIR = "/tmp/line_bot_images"
os.makedirs(IMAGE_DIR, exist_ok=True)

FONT_FILENAME = os.getenv("FONT_FILENAME", "Sarabun-Regular.ttf")
FONT_PATH = os.path.join(os.getcwd(), FONT_FILENAME)
try:
    if ImageFont and FONT_PATH:
        try:
            ImageFont.truetype(FONT_PATH, 12)
            app.logger.info(f"Custom font loaded from {FONT_PATH}")
        except Exception:
            FONT_PATH = None
            app.logger.warning(f"Font {FONT_FILENAME} not found. Using default font.")
except Exception:
    FONT_PATH = None

# Collections and constants
PERSONNEL_COLLECTION = "personnel"
DUTY_COLLECTION = "duty_rotation"
LEAVE_COLLECTION = "line_duty_leave"
SESSION_COLLECTION = "user_sessions"
DUTY_LOGS_COLLECTION = "duty_logs"
LEAVE_TYPES = ["ลาพัก", "ลากิจ", "ลาป่วย", "ราชการ"]

STATUS_PENDING = "Pending"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"

# --- Helpers ---
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
    leave_list = get_leaves_on_date(date_str)
    leave_map = {leave['personnel_name']: leave['leave_type'] for leave in leave_list}
    available_personnel = [p for p in personnel if p.get('name') not in leave_map]
    if not available_personnel:
        assignments = []
        for name, leave_type in leave_map.items():
            assignments.append({
                "duty": f"ลา ({leave_type})",
                "name": name,
                "color": "#FF0000",
                "status": "ลา"
            })
        return assignments
    available_personnel.sort(key=lambda x: x.get("duty_priority", 999))
    num_personnel = len(available_personnel)
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

# --- Admin LINE handlers omitted in this listing for brevity (they remain implemented earlier) ---
# For LINE webhook/message handlers, we assume handler and line_bot_api set up above.
# ... (LINE handlers code is included in the full app in previous messages.)

# -----------------------------
# REST CRUD API Endpoints (/api)
# -----------------------------
def admin_required():
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

# Duties CRUD
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
        status = request.args.get("status")
        line_id = request.args.get("line_id")
        personnel_name = request.args.get("personnel_name")
        if status:
            q = q.where("status", "==", status)
        if line_id:
            q = q.where("line_id", "==", line_id)
        if personnel_name:
            q = q.where("personnel_name", "==", personnel_name)
        docs = q.stream()
        items = []
        date_filter = request.args.get("date")
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

# Health-check
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "firebase": bool(db)})

if __name__ == "__main__":
    # dev server (not for production) - use gunicorn for production
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)


