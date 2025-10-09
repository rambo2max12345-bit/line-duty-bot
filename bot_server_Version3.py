# -*- coding: utf-8 -*-

# ========================================================================================
# LINE Bot จัดตารางเวร (ปรับปรุงให้มี CRUD ฟังก์ชันสำหรับ "leaves" และ "personnel")
# - เพิ่ม REST API endpoints สำหรับ Create / Read / Update / Delete (leaves และ personnel)
# - ใช้ Firebase Firestore ถ้ามีการตั้งค่า FIREBASE_CREDENTIALS_JSON ใน env
# - ถ้าไม่มี Firebase จะใช้ in-memory store (ไม่ถาวร) เพื่อทดสอบและพัฒนา
# ========================================================================================

from flask import Flask, request, abort, send_from_directory, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    PostbackEvent
)
import os
import json
from datetime import datetime, timedelta
import uuid
import logging

import firebase_admin
from firebase_admin import credentials, firestore

from dotenv import load_dotenv
load_dotenv()  # อ่านตัวแปรจาก .env

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

# --- ตั้งค่า LINE จาก env ---
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# Ensure handler has an .add decorator even if secret is missing
if CHANNEL_SECRET:
    handler = WebhookHandler(CHANNEL_SECRET)
else:
    class _NoopHandler:
        def add(self, *args, **kwargs):
            def decorator(f):
                return f
            return decorator
        def handle(self, body, signature):
            raise Exception("Handler not configured")
    handler = _NoopHandler()

if CHANNEL_ACCESS_TOKEN:
    line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
else:
    class _NoopLineApi:
        def reply_message(self, reply_token, message):
            app.logger.info(f"reply_message called but LINE not configured. reply_token={reply_token} message={message}")
    line_bot_api = _NoopLineApi()

# --- เชื่อม Firebase (ถ้ามี) ---
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
    db = None
    app.logger.error(f"Firebase connection failed: {e}")

# --- หน่วยความจำและรายชื่อ (ตัวอย่างสั้น ๆ เพื่อให้รันได้) ---
user_states = {}
personnel_list = [
    "อส.ทพ.บุญธรรม เขียวเข็ม",
    "อส.ทพ.สนธยา ปราบณรงค์",
    "อส.ทพ.คเนศ เกียรติขวัญบุ",
    "อส.ทพ.ณัฐพล แสวงทรัพย์",
    "อส.ทพ.อาวุธ มณี"
]

# In-memory store สำหรับ leaves เมื่อ Firebase ไม่พร้อม (key: id -> record)
leaves_store = {}

# --- ตรวจสอบ/สร้างโฟลเดอร์รูปภาพที่ใช้ serve ---
IMAGE_DIR = '/tmp/line_bot_images'
os.makedirs(IMAGE_DIR, exist_ok=True)

# --- Serve Image ---
@app.route("/images/<path:filename>")
def serve_image(filename):
    # ใช้ send_from_directory เพื่อส่งไฟล์จาก IMAGE_DIR
    try:
        return send_from_directory(IMAGE_DIR, filename)
    except Exception as e:
        app.logger.error(f"serve_image error: {e}")
        abort(404)

# --- หน้า index / health ---
@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "status": "ok",
        "firebase_connected": db is not None,
        "has_line_config": bool(CHANNEL_ACCESS_TOKEN and CHANNEL_SECRET)
    })

# --- Webhook ---
@app.route("/webhook", methods=['POST'])
def callback():
    if handler is None or line_bot_api is None:
        app.logger.error("LINE config missing. Cannot handle webhook.")
        return "LINE config missing", 500

    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature.")
        abort(400)
    except LineBotApiError as e:
        app.logger.error(f"LineBotApiError handling event: {e}")
        abort(500)
    except Exception as e:
        app.logger.error(f"Unexpected error handling webhook: {e}")
        abort(500)
    return 'OK'

# --- ช่วยแปลง user id ให้ปลอดภัย ---
def get_user_id_from_event(event):
    try:
        uid = event.source.user_id
        if not uid:
            # บางกรณี (group/room) อาจไม่มี user_id
            uid = f"{event.source.type}:{getattr(event.source, 'group_id', getattr(event.source, 'room_id', 'unknown'))}"
        return uid
    except Exception:
        return "unknown"

# --- Firestore / In-memory CRUD helpers for 'leaves' ---
def create_leave_record(record: dict):
    # record: dict with leave_type, leave_date, note, user_id, created_at (optional)
    if db:
        try:
            doc_ref = db.collection("leaves").document()
            now = datetime.utcnow().isoformat()
            record.setdefault("created_at", now)
            doc_ref.set(record)
            app.logger.info(f"Created leave in Firestore: {doc_ref.id}")
            return doc_ref.id
        except Exception as e:
            app.logger.error(f"Failed to create leave in Firestore: {e}")
            # fallback to in-memory
    # in-memory fallback
    lid = str(uuid.uuid4())
    record.setdefault("created_at", datetime.utcnow().isoformat())
    leaves_store[lid] = record
    app.logger.info(f"Created leave in memory: {lid}")
    return lid

def get_leave_record(lid: str):
    if db:
        try:
            doc = db.collection("leaves").document(lid).get()
            if doc.exists:
                data = doc.to_dict()
                data["id"] = doc.id
                return data
            return None
        except Exception as e:
            app.logger.error(f"Failed to read leave from Firestore: {e}")
    # fallback in-memory
    rec = leaves_store.get(lid)
    if rec:
        r = dict(rec)
        r["id"] = lid
        return r
    return None

def list_leaves():
    results = []
    if db:
        try:
            docs = db.collection("leaves").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
            for d in docs:
                item = d.to_dict()
                item["id"] = d.id
                results.append(item)
            return results
        except Exception as e:
            app.logger.error(f"Failed to list leaves from Firestore: {e}")
    # fallback in-memory
    for lid, rec in leaves_store.items():
        item = dict(rec)
        item["id"] = lid
        results.append(item)
    # sort by created_at desc if possible
    try:
        results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    except Exception:
        pass
    return results

def update_leave_record(lid: str, updates: dict):
    if db:
        try:
            doc_ref = db.collection("leaves").document(lid)
            if not doc_ref.get().exists:
                return False
            updates["updated_at"] = datetime.utcnow().isoformat()
            doc_ref.update(updates)
            return True
        except Exception as e:
            app.logger.error(f"Failed to update leave in Firestore: {e}")
    # fallback in-memory
    if lid in leaves_store:
        leaves_store[lid].update(updates)
        leaves_store[lid]["updated_at"] = datetime.utcnow().isoformat()
        return True
    return False

def delete_leave_record(lid: str):
    if db:
        try:
            doc_ref = db.collection("leaves").document(lid)
            if not doc_ref.get().exists:
                return False
            doc_ref.delete()
            return True
        except Exception as e:
            app.logger.error(f"Failed to delete leave in Firestore: {e}")
    # fallback in-memory
    if lid in leaves_store:
        del leaves_store[lid]
        return True
    return False

# --- CRUD endpoints for leaves ---
@app.route("/api/leaves", methods=["POST"])
def api_create_leave():
    if not request.is_json:
        return jsonify({"error": "Expected JSON body"}), 400
    body = request.get_json()
    # minimal validation
    leave_type = body.get("leave_type")
    leave_date = body.get("leave_date")
    user_id = body.get("user_id", "anonymous")
    note = body.get("note", "")
    if not leave_type or not leave_date:
        return jsonify({"error": "leave_type and leave_date are required"}), 400
    rec = {
        "leave_type": leave_type,
        "leave_date": leave_date,
        "note": note,
        "user_id": user_id
    }
    lid = create_leave_record(rec)
    return jsonify({"id": lid, "record": rec}), 201

@app.route("/api/leaves", methods=["GET"])
def api_list_leaves():
    items = list_leaves()
    return jsonify(items), 200

@app.route("/api/leaves/<lid>", methods=["GET"])
def api_get_leave(lid):
    rec = get_leave_record(lid)
    if not rec:
        return jsonify({"error": "not found"}), 404
    return jsonify(rec), 200

@app.route("/api/leaves/<lid>", methods=["PUT", "PATCH"])
def api_update_leave(lid):
    if not request.is_json:
        return jsonify({"error": "Expected JSON body"}), 400
    updates = request.get_json()
    allowed = {"leave_type", "leave_date", "note"}
    payload = {k: v for k, v in updates.items() if k in allowed}
    if not payload:
        return jsonify({"error": "No updatable fields provided"}), 400
    ok = update_leave_record(lid, payload)
    if not ok:
        return jsonify({"error": "not found or update failed"}), 404
    return jsonify({"id": lid, "updated": payload}), 200

@app.route("/api/leaves/<lid>", methods=["DELETE"])
def api_delete_leave(lid):
    ok = delete_leave_record(lid)
    if not ok:
        return jsonify({"error": "not found or delete failed"}), 404
    return jsonify({"id": lid, "deleted": True}), 200

# --- Simple CRUD for personnel (in-memory) ---
# For now personnel_list is in-memory. You can wire this to Firestore similarly if needed.
@app.route("/api/personnel", methods=["GET"])
def api_list_personnel():
    # return list of personnel with generated ids
    data = [{"id": str(i), "name": n} for i, n in enumerate(personnel_list, start=1)]
    return jsonify(data), 200

@app.route("/api/personnel", methods=["POST"])
def api_create_personnel():
    if not request.is_json:
        return jsonify({"error": "Expected JSON body"}), 400
    name = request.get_json().get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    personnel_list.append(name)
    return jsonify({"id": len(personnel_list), "name": name}), 201

@app.route("/api/personnel/<int:pid>", methods=["PUT", "PATCH"])
def api_update_personnel(pid):
    idx = pid - 1
    if idx < 0 or idx >= len(personnel_list):
        return jsonify({"error": "not found"}), 404
    if not request.is_json:
        return jsonify({"error": "Expected JSON body"}), 400
    name = request.get_json().get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    personnel_list[idx] = name
    return jsonify({"id": pid, "name": name}), 200

@app.route("/api/personnel/<int:pid>", methods=["DELETE"])
def api_delete_personnel(pid):
    idx = pid - 1
    if idx < 0 or idx >= len(personnel_list):
        return jsonify({"error": "not found"}), 404
    name = personnel_list.pop(idx)
    return jsonify({"id": pid, "name": name, "deleted": True}), 200

# --- Message Event Handler ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = get_user_id_from_event(event)
    user_message = (event.message.text or "").strip()
    app.logger.info(f"[message] from {user_id}: {user_message}")

    # คำสั่งยกเลิก
    if user_message == "#ยกเลิก":
        if user_id in user_states:
            del user_states[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="❌ ยกเลิกคำสั่งเรียบร้อยแล้ว"))
        return

    # คำสั่งเริ่มต้นแจ้งลา
    if user_message == "#แจ้งลา":
        user_states[user_id] = {"step": "awaiting_leave_type", "data": {}}
        leave_buttons = [
            QuickReplyButton(action=MessageAction(label="ลาพัก", text="ลาพัก")),
            QuickReplyButton(action=MessageAction(label="ลากิจ", text="ลากิจ")),
            QuickReplyButton(action=MessageAction(label="ลาป่วย", text="ลาป่วย")),
            QuickReplyButton(action=MessageAction(label="ราชการ", text="ราชการ")),
            QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
        ]
        reply_msg = TextSendMessage(text="กรุณาเลือกประเภทการลาครับ", quick_reply=QuickReply(items=leave_buttons))
        line_bot_api.reply_message(event.reply_token, reply_msg)
        return

    # รีเซ็ตสถานะสำหรับผู้ใช้
    if user_message == "#รีเซ็ต":
        if user_id in user_states:
            del user_states[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🔄️ รีเซ็ตเรียบร้อยแล้วครับ"))
        return

    # ถ้ามีสถานะรันอยู่ ให้จัดการ flow
    if user_id in user_states:
        state = user_states[user_id]
        step = state.get("step", "")
        # ถ้ารอประเภทการลา (มักจะได้จาก quick reply)
        if step == "awaiting_leave_type":
            leave_type = user_message
            if leave_type.lower() in ("ลาพัก", "ลากิจ", "ลาป่วย", "ราชการ"):
                state["data"]["type"] = leave_type
                state["step"] = "awaiting_leave_date"
                quicks = [
                    QuickReplyButton(action=MessageAction(label="วันนี้", text="วันนี้")),
                    QuickReplyButton(action=MessageAction(label="พรุ่งนี้", text="พรุ่งนี้")),
                    QuickReplyButton(action=MessageAction(label="❌ ยกเลิก", text="#ยกเลิก"))
                ]
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="กรุณาระบุวันที่ลา (พิมพ์ YYYY-MM-DD หรือเลือกวันนี้/พรุ่งนี้)", quick_reply=QuickReply(items=quicks))
                )
            else:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="ไม่พบประเภทการลา กรุณาเลือกอีกครั้ง หรือพิมพ์ #ยกเลิก เพื่อยกเลิก"))
            return

        # ถ้ารอวันที่
        if step == "awaiting_leave_date":
            date_text = user_message
            try:
                if date_text == "วันนี้":
                    leave_date = datetime.utcnow().date()
                elif date_text == "พรุ่งนี้":
                    leave_date = (datetime.utcnow().date() + timedelta(days=1))
                else:
                    leave_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                state["data"]["date"] = leave_date.isoformat()
                state["step"] = "awaiting_leave_note"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="กรุณาระบุหมายเหตุ/เหตุผลการลา (หรือพิมพ์ - หากไม่ต้องการใส่)"))
            except Exception:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="รูปแบบวันที่ไม่ถูกต้อง กรุณาพิมพ์ YYYY-MM-DD หรือเลือก 'วันนี้'/'พรุ่งนี้'"))
            return

        # ถ้ารอหมายเหตุ
        if step == "awaiting_leave_note":
            note = user_message if user_message != "-" else ""
            state["data"]["note"] = note
            # สร้าง record
            rec = {
                "user_id": user_id,
                "leave_type": state["data"].get("type"),
                "leave_date": state["data"].get("date"),
                "note": note,
                "created_at": datetime.utcnow().isoformat()
            }
            lid = create_leave_record(rec)
            # ตอบยืนยัน
            text_lines = [
                "✅ บันทึกการลาเรียบร้อยแล้ว",
                f"ID: {lid}",
                f"ประเภท: {rec['leave_type']}",
                f"วันที่: {rec['leave_date']}",
            ]
            if note:
                text_lines.append(f"หมายเหตุ: {note}")
            if db:
                text_lines.append("(บันทึกลง Firebase เรียบร้อยแล้ว)")
            else:
                text_lines.append("(บันทึกลงหน่วยความจำในเครื่อง — ไม่ถาวร)")
            # ล้างสถานะ
            if user_id in user_states:
                del user_states[user_id]
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(text_lines)))
            return

    # ถ้าไม่มี flow ใด ๆ ให้ตอบ help message
    help_text = (
        "สวัสดีครับ 👋\n"
        "คำสั่งที่ใช้งานได้:\n"
        "- #แจ้งลา : เริ่มกระบวนการแจ้งลา\n"
        "- #ยกเลิก : ยกเลิกคำสั่งปัจจุบัน\n"
        "- #รีเซ็ต : รีเซ็ตสถานะของคุณ\n\n"
        "นอกจากนี้มี API CRUD สำหรับ leaves และ personnel ที่ /api/…"
    )
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=help_text))


# --- Postback Event Handler ---
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = get_user_id_from_event(event)
    data = event.postback.data or ""
    params = event.postback.params or {}
    app.logger.info(f"[postback] from {user_id}: data={data}, params={params}")
    try:
        reply = f"Postback received.\nData: {data}\nParams: {json.dumps(params)}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    except Exception as e:
        app.logger.error(f"Error replying to postback: {e}")

# --- Run Server ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.logger.info(f"Starting server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port)