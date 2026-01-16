import logging
from aiogram import Bot
from aiogram.types import Message
from aiogram.dispatcher.router import Router
import asyncio

# ✅ טוקן מה-BotFather
TELEGRAM_BOT_TOKEN = "8031412017:AAFDQ400OeX-ufhEOR7afjEWRl1wCDfE2No"

# ✅ רשימת Chat IDs – הוסף כאן כל מי שצריך לקבל הודעה
CHAT_IDS = [
    5817603930,     # אתה
    1880599224      # משתמש נוסף
]

# ✅ יצירת אובייקט הבוט
bot = Bot(token=TELEGRAM_BOT_TOKEN)
router = Router()  # aiogram 3.x

async def send_telegram_message(message: str):
    """📌 שולח הודעה לטלגרם לכל המשתמשים ברשימה"""
    try:
        for chat_id in CHAT_IDS:
            await bot.send_message(chat_id, f"🔔 <b>עדכון מערכת:</b>\n{message}", parse_mode="HTML")
        print("✅ הודעה נשלחה לכל המשתמשים בטלגרם")
    except Exception as e:
        logging.error(f"❌ שגיאה בשליחת הודעה לטלגרם: {e}")

# ✅ בדיקה ידנית
if __name__ == "__main__":
    asyncio.run(send_telegram_message("🚀 הודעת בדיקה – האם זה עובד?"))
