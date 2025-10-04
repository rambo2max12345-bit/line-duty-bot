# -*- coding: utf-8 -*-
from flask import Flask, request, abort
from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
import os

CHANNEL_ACCESS_TOKEN = os.environ.get('CHANNEL_ACCESS_TOKEN', '8Qa3lq+KjkF68P1W6xAkkuRyoXpz9YyuQI2nOKJRu/ndsvfGLZIft6ltdgYV8vMEbBkz5AWzYoF+CaS7u0OShm uZvo5Yufb6+Xvr4gBti4Gc4cp45MCnyD0cte94vZyyEhLKC3WJKvd9usUXqCwrOgdB04t89/1O/w1cDnyilFU=')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET', '1d0c51790d0bff2b98dbb98dc8f72663')

app = Flask(__name__)
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

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
    user_message = event.message.text
    if user_message == '#Bot01':
        quick_reply_buttons = QuickReply(items=[
            QuickReplyButton(action=MessageAction(label="📝 แจ้งลา/ราชการ", text="#แจ้งลา")),
            QuickReplyButton(action=MessageAction(label="🗓️ จัดเวรประจำวัน", text="#จัดเวร")),
            QuickReplyButton(action=MessageAction(label="📄 ดูข้อมูลการลา", text="#ดูข้อมูลลา"))
        ])
        reply_message = TextSendMessage(
            text="มีอะไรให้รับใช้ครับนายท่าน",
            quick_reply=quick_reply_buttons
        )
        line_bot_api.reply_message(event.reply_token, reply_message)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)