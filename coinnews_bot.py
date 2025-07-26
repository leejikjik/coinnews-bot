import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# 로깅 설정
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger()

def start(update: Update, context: CallbackContext) -> None:
    logger.info("Received /start command from user: %s", update.message.from_user.username)  # 로그 기록
    update.message.reply_text('Hello, I am your bot!')

def news(update: Update, context: CallbackContext) -> None:
    logger.info("Received /news command from user: %s", update.message.from_user.username)  # 로그 기록
    # 뉴스 정보를 처리하는 코드 추가
    update.message.reply_text('Fetching the latest news...')

def price(update: Update, context: CallbackContext) -> None:
    logger.info("Received /price command from user: %s", update.message.from_user.username)  # 로그 기록
    # 가격 데이터를 처리하는 코드 추가
    update.message.reply_text('Fetching price data...')

def main():
    # 텔레그램 봇 토큰을 넣어주세요
    updater = Updater("YOUR_BOT_TOKEN", use_context=True)
    
    dp = updater.dispatcher
    
    # 명령어 처리기 추가
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("news", news))
    dp.add_handler(CommandHandler("price", price))

    # 봇 시작
    updater.start_polling()

    # 봇이 계속 실행되도록 대기
    updater.idle()

if __name__ == '__main__':
    main()
