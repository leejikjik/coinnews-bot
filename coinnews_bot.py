import os
import logging
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# 로그 설정
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# 환경변수
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# Flask 앱 (Render용 KeepAlive)
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Telegram Bot is running."

# /getid 명령어
async def getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_type = chat.type
    chat_id = chat.id

    chat_type_label = {
        "private": "👤 개인 채팅",
        "group": "👥 그룹 채팅",
        "supergroup": "👥 슈퍼그룹 채팅",
        "channel": "📢 채널"
    }.get(chat_type, "❓알 수 없음")

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ 현재 채팅 정보\n\n📌 Chat Type: {chat_type_label}\n🆔 Chat ID: `{chat_id}`",
        parse_mode="Markdown"
    )

# 봇 실행 함수
def run_bot():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("getid", getid))
    app.run_polling()

# Flask 실행 함수
def run_flask():
    flask_app.run(host="0.0.0.0", port=8080)

# 병렬 실행
if __name__ == "__main__":
    Thread(target=run_flask).start()
    run_bot()
