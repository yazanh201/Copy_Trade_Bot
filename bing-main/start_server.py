import asyncio
import threading
import os
from Web.app import app  # אפליקציית Flask שלך
from services.trade_manager import TradeManager

import logging
logging.getLogger('werkzeug').disabled = True

# ⚙ פונקציה להרצת TradeManager
async def run_trade_manager():
    manager = TradeManager()
    loop = asyncio.get_event_loop()
    manager.start_background_tasks(loop)  # ✅ העברת הלולאה הנוכחית
    await manager.load_state()

    try:
        await manager.sync_trades()
    except Exception as e:
        print(f"❌ שגיאה ב־TradeManager: {e}")
    finally:
        await manager.close()

# 🎯 הרצת trade_manager בתוך Thread נפרד עם לולאת asyncio
def start_trade_manager():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_trade_manager())

if __name__ == "__main__":  # ← זה התיקון החשוב
    # 🔁 הרץ את TradeManager ברקע
    threading.Thread(target=start_trade_manager, daemon=True).start()

    # 🌐 הרץ את Flask בענן (Render)
    port = int(os.environ.get("PORT", 5000))  # Render מגדיר PORT בסביבה
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)