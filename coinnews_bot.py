from telegram import Update
from telegram.ext import CommandHandler, ApplicationBuilder, ContextTypes

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    print(f"[📥 CHAT ID] {chat_id}")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"✅ 이 채팅의 chat_id는 `{chat_id}` 입니다.",
        parse_mode="Markdown"
    )

# 명령어 등록
application.add_handler(CommandHandler("getid", get_chat_id))
