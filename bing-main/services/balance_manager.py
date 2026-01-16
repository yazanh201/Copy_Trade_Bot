import asyncio
import time
from core.logger import logger


class BalanceManager:
    def __init__(self):
        self.balance_cache = {}  # {client_name: (balance_data, timestamp)}
        self.open_orders_cache = {}  # {"symbol": (orders, timestamp)}
        self.master_positions_cache = (None, 0)

                # ✅ תור לקריאות API של המאסטר
        self.master_api_queue = asyncio.Queue()
        self.api_worker_started = False



    async def get_cached_balance(self, client, asset="USDT", ttl=20):
        name = client.get("name", "לא ידוע")
        now = time.time()

        # ודא שהמילון של ה-locks קיים
        if not hasattr(self, "balance_locks"):
            self.balance_locks = {}

        # צור lock אם אין
        if name not in self.balance_locks:
            self.balance_locks[name] = asyncio.Lock()

        # שליפה מהקאש לפני כניסה ל-lock
        cached = self.balance_cache.get(name)
        if cached and now - cached[1] < ttl:
            return cached[0]

        async with self.balance_locks[name]:
            # בדיקה חוזרת לאחר ההמתנה ל-lock
            cached = self.balance_cache.get(name)
            if cached and now - cached[1] < ttl:
                return cached[0]

            try:
                api = client.get("api")
                if api is None:
                    raise ValueError("🔐 אין API תקף ללקוח")

                # תוסיף timeout למקרה של תקיעה ב־API
                balance_data = await asyncio.wait_for(
                    api.get_balance_details(asset),
                    timeout=5
                )

                self.balance_cache[name] = (balance_data, time.time())
                #logger.info(f"✅ balance עודכן ללקוח {name}")
                return balance_data

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout בקבלת balance מלקוח {name}")
                return {"available": 0}

            except Exception as e:
                logger.warning(f"⚠️ שגיאה בקבלת balance מלקוח {name}: {e}")
                return {"available": 0}



    async def get_cached_open_orders(self, master_api, symbol, ttl=12):
        now = time.time()

        # ודא שהמילון של locks קיים
        if not hasattr(self, "open_orders_locks"):
            self.open_orders_locks = {}

        # יצירת lock חדש אם לא קיים
        if symbol not in self.open_orders_locks:
            self.open_orders_locks[symbol] = asyncio.Lock()

        # ניסיון ראשון לקרוא מהקאש לפני המתנה ל-lock
        cached = self.open_orders_cache.get(symbol)
        if cached and now - cached[1] < ttl:
            return cached[0]

        async with self.open_orders_locks[symbol]:
            # בדיקה חוזרת לאחר ההמתנה ל-lock
            cached = self.open_orders_cache.get(symbol)
            if cached and now - cached[1] < ttl:
                return cached[0]

            try:
                # הפעלת הקריאה עם timeout כדי למנוע תקיעות
                orders = await asyncio.wait_for(
                    self.enqueue_master_api_call(lambda: master_api.get_trade_parameters(symbol)),
                    timeout=5
                )
                self.open_orders_cache[symbol] = (orders, time.time())
                #logger.info(f"✅ openOrders עודכנו עבור {symbol}")
                return orders

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout בשליפת openOrders עבור {symbol}")
                return []

            except Exception as e:
                logger.warning(f"⚠️ שגיאה בשליפת openOrders עבור {symbol}: {e}")
                return []




    async def get_cached_master_positions(self, master_api, ttl=0.8):
        now = time.time()
        positions, last_time = self.master_positions_cache

        if positions and now - last_time < ttl:
            return positions

        try:
            positions = await self.enqueue_master_api_call(lambda: master_api.get_positions())
            self.master_positions_cache = (positions, now)
            return positions

        except Exception as e:
            logger.warning(f"⚠️ שגיאה בעת שליפת פוזיציות מהמאסטר: {e}")
            return []  # כדי לא לשבור את הזרימה




    async def enqueue_master_api_call(self, coro_func):
        """מכניס קריאה לתור ומחזיר את התוצאה"""
        try:
            fut = asyncio.get_event_loop().create_future()
            await self.master_api_queue.put((coro_func, fut))

            # הפעלת עובד התור רק פעם אחת
            if not self.api_worker_started:
                asyncio.create_task(self.api_worker())
                self.api_worker_started = True

            return await fut

        except Exception as e:
            logger.error(f"🚫 שגיאה בהכנסת קריאה לתור המאסטר: {e}")
            raise e  # חשוב כדי שהשגיאה תמשיך למי שקרא לפונקציה

    async def api_worker(self):
        """עובד שמבצע קריאות מהתור אחת כל X זמן"""
        while True:
            try:
                coro_func, fut = await self.master_api_queue.get()
                try:
                    result = await coro_func()
                    fut.set_result(result)
                except Exception as e:
                    logger.warning(f"⚠️ שגיאה בביצוע קריאת API מהממתין בתור: {e}")
                    fut.set_exception(e)
                finally:
                    await asyncio.sleep(0.3)  # ⚙️ שליטה על קצב הקריאות (5 בשנייה)
                    self.master_api_queue.task_done()

            except Exception as e:
                logger.error(f"🚫 שגיאה כללית בתור ה־API של המאסטר: {e}", exc_info=True)
