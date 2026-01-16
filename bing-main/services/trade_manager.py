import time
import asyncio
from utils.bingx_api import BingXAPI
from services.trade_operations import TradeOperations  # ✅ מייבא את המחלקה החדשה
from services.trade_state_mongo import TradeStateMongoManager  # ✅ שימוש במונגו
import aiohttp
from load_apis_from_db import load_apis_from_db  # נניח ששמרת את הפונקציה בקובץ בשם זה
from core.logger import logger
from services.trade_math_utils import calculate_master_pct_by_available_margin
from services.balance_manager import BalanceManager




class TradeManager:

    def __init__(self):
        #logger.info("📌 TradeManager הופעל!")
        self.balance_manager = BalanceManager()

        config = load_apis_from_db()
        self.clients = []
        self.last_clients_refresh_time = 0
        self.clients_refresh_interval = 10  # שניות



        # 🔵 יצירת session משותף
        self.shared_session = aiohttp.ClientSession()

        # 🧠 אתחול המאסטר והלקוחות עם אותו session
        self.master_api = BingXAPI(config["master"]["api_key"], config["master"]["secret_key"], session=self.shared_session)
        self.clients = [
            {"name": client["name"], "api": BingXAPI(client["api_key"], client["secret_key"], session=self.shared_session)}
            for client in config["clients"]
        ]

        self.last_positions = {}
        self.copied_trades = {}
        self.queue = asyncio.Queue()
        self.client_positions = {}
        self.closed_trades = set()
        self.client_balances = {}  # ⬅️ זיכרון מקומי ליתרות הלקוחות


        # ✅ מחובר למונגו
        self.mongo_state = TradeStateMongoManager()

        self.trade_operations = TradeOperations(
            self.master_api,
            self.clients,
            self.last_positions,
            self.client_positions,
            self.copied_trades,
            self.closed_trades,
            save_state_func=self.save_state
        )



    def load_clients(self):
        config = load_apis_from_db()
        return [
            {"name": client["name"], "api": BingXAPI(client["api_key"], client["secret_key"], session=self.shared_session)}
            for client in config["clients"]
        ]


    def refresh_clients_if_needed(self):
        now = time.time()
        if now - self.last_clients_refresh_time > self.clients_refresh_interval:
            #logger.info("🔄 טוען מחדש את הלקוחות (אוטומטית)")
            self.clients = self.load_clients()
            self.trade_operations.update_clients(self.clients)
            self.last_clients_refresh_time = now


    async def save_state(self):
        try:
            state_data = {
                "last_positions": self.last_positions,
                "copied_trades": self.copied_trades,
                "client_positions": self.trade_operations.client_positions,
                "closed_trades": list(self.closed_trades)
            }

            await self.mongo_state.save_state(state_data)
            #logger.info("📂 מצב נשמר למונגו בהצלחה")
        except Exception as e:
            logger.error(f"❌ שגיאה בשמירת מצב למונגו: {e}")

    async def load_state(self):
        try:
            data = await self.mongo_state.load_state()
            self.last_positions = data.get("last_positions", {})
            self.copied_trades = data.get("copied_trades", {})
            self.client_positions = data.get("client_positions", {})
            self.closed_trades = set(data.get("closed_trades", []))

            # ✅ מסנכרן גם את TradeOperations
            self.trade_operations.last_positions = self.last_positions
            self.trade_operations.client_positions = self.client_positions
            self.trade_operations.copied_trades = self.copied_trades
            self.trade_operations.closed_trades = self.closed_trades

            #logger.info(f"📦 מצב נטען: {len(self.client_positions)} לקוחות עם פוזיציות")

        except Exception as e:
            logger.error(f"❌ שגיאה בטעינת מצב ממונגו: {e}")
            self.last_positions = {}
            self.copied_trades = {}
            self.client_positions = {}
            self.closed_trades = set()


    async def process_trade_queue(self):
        #logger.info("📌 התחלת תהליך עיבוד עסקאות בתור")

        try:
            # יצירת מספר תהליכי עיבוד במקביל
            workers = [asyncio.create_task(self.trade_worker(i)) for i in range(5)]
            await self.queue.join()  # מחכה לסיום כל המשימות בתור

            for worker in workers:
                worker.cancel()

            #logger.info("✅ כל העסקאות שהיו בתור עובדו בהצלחה")

        except Exception as e:
            logger.exception(f"❌ שגיאה כללית בתהליך עיבוד התור: {e}")


    async def sync_trades(self):
        """
        פונקציית סנכרון בין עסקאות המאסטר ללקוחות.

        הפעולה בודקת בכל לולאה את הפוזיציות הפתוחות של המאסטר,
        משווה אותן למצב האחרון, ומבצעת את הפעולות הבאות:
        1. פתיחת עסקה חדשה ללקוחות אם נפתחה במאסטר.
        2. עדכון מינוף ומצב Margin אם זה חדש.
        3. סגירה חלקית אם הכמות ירדה משמעותית.
        4. סגירה מלאה ללקוחות אם עסקה נסגרה במאסטר.
        """

        while True:
            try:
                # שליפת פוזיציות נוכחיות של המאסטר מה-API (כולל cache)
                positions = await self.balance_manager.get_cached_master_positions(self.master_api)
            except Exception as e:
                logger.error(f"❌ שגיאה בשליפת פוזיציות מהמאסטר: {e}")
                await asyncio.sleep(1)
                continue

            # בדיקת תקינות הפוזיציות
            if not positions or positions.get("code") != 0 or "data" not in positions:
                logger.warning(f"⚠️ נתוני פוזיציות לא תקינים או ריקים: {positions}")
                await asyncio.sleep(1)
                continue

            try:
                open_positions = {}  # מצב נוכחי של פוזיציות פתוחות

                for position in positions["data"]:
                    try:
                        qty = float(position.get("positionAmt", 0))
                        if qty == 0:
                            continue  # התעלמות מפוזיציות סגורות

                        # שליפה וניתוח נתוני הפוזיציה
                        symbol = position["symbol"]
                        position_side = position["positionSide"]
                        side = "BUY" if position_side.upper() == "SHORT" else "SELL"
                        leverage = int(position.get("leverage", 0))
                        isolated = position.get("isolated", False)
                        unrePNL = position.get("unrealizedProfit")
                        price = float(position["markPrice"])
                        Leverage, tp, sl = await self.balance_manager.get_cached_open_orders(self.master_api, symbol)
                        position_value = float(position["positionValue"])

                        # שליפת יתרת מאסטר
                        master_client = {"name": "master", "api": self.master_api}
                        master_balances = await self.balance_manager.get_cached_balance(master_client, "USDT")
                        master_balance = float(master_balances.get("available", 0))

                        # חישוב אחוז ההשקעה של המאסטר
                        master_pct = calculate_master_pct_by_available_margin(position_value, leverage, master_balance)

                        if leverage <= 0:
                            continue

                        # בדיקת סגירה חלקית
                        if symbol in self.last_positions:
                            prev_qty = self.last_positions[symbol].get("qty", 0)
                            if prev_qty > 0 and qty < prev_qty * 0.9:
                                master_closed_pct = (prev_qty - qty) / prev_qty
                                await self.trade_operations.close_partial_trades(symbol, master_closed_pct, side, position_side)

                        # שמירת הפוזיציה החדשה
                        open_positions[symbol] = {
                            "qty": qty,
                            "side": side,
                            "position_side": position_side,
                            "leverage": leverage,
                            "tp": tp,
                            "sl": sl,
                            "isolated": isolated,
                            "unrealizedProfit": unrePNL
                        }

                        # פתיחת עסקה חדשה אם טרם שוכפלה
                        if symbol not in self.copied_trades:
                            await self.queue.put((symbol, side, position_side, master_pct, price, leverage, tp, sl , isolated))
                            self.copied_trades[symbol] = True
                            await self.save_state()

                    except Exception as e:
                        logger.warning(f"⚠️ שגיאה בעיבוד סימבול: {e}")

                # התחלת תהליך פתיחת עסקאות (אם קיימות בתור)
                if not self.queue.empty():
                    asyncio.create_task(self.process_trade_queue())

                # איתור עסקאות שנסגרו אצל המאסטר, וסגירתן אצל הלקוחות
                closed_positions = {
                    sym: pos for sym, pos in self.last_positions.items()
                    if sym not in open_positions
                }
                if closed_positions:
                    for symbol in closed_positions:
                        await self.trade_operations.close_trades(symbol)
                        self.copied_trades.pop(symbol, None)
                    await self.save_state()


                # עדכון מצב אחרון
                self.last_positions = open_positions
                await self.save_state()

            except Exception as e:
                logger.exception(f"❌ שגיאה כללית במהלך sync_trades: {e}")

            # השהייה קטנה עד הסיבוב הבא
            await asyncio.sleep(0.1)


    async def trade_worker(self, worker_id):
        while True:
            try:
                symbol, side, position_side, master_pct, price, leverage , tp, sl , isolated = await self.queue.get()
                #logger.info(f"👷‍♂️ עובד #{worker_id} מבצע עסקה: {symbol} ({side}), כמות: {qty}")
                await self.trade_operations.copy_trade(symbol, side, position_side, master_pct,price,leverage,tp, sl , isolated)
                self.queue.task_done()

            except Exception as e:
                logger.exception(f"❌ עובד #{worker_id} - שגיאה בטיפול בעסקה מהתור: {e}")
                self.queue.task_done()  # גם אם יש שגיאה, נציין שסיימנו כדי שהתור לא ייתקע


    async def preload_balances(self, clients, asset="USDT"):
        """📊 טעינת יתרות עם השהייה בין כל לקוח – עמיד ויציב"""
        balances = {}

        for client in clients:
            name = client.get("name", "לא ידוע")
            try:
                balance_data = await self.balance_manager.get_cached_balance(client, asset)

                if isinstance(balance_data, dict) and "available" in balance_data:
                    balances[name.lower()] = balance_data
                    #logger.info(f"✅ יתרה ללקוח {name}: {balance_data.get('available')} USDT")
                else:
                    logger.warning(f"⚠️ תגובת יתרה לא תקינה ללקוח {name}: {balance_data}")
                    balances[name.lower()] = {"available": 0}

            except Exception as e:
                logger.warning(f"⚠️ שגיאה בטעינת יתרה מראש ללקוח {name}: {e}")
                balances[name.lower()] = {"available": 0}

            await asyncio.sleep(1.5)  # ⏱️ השהייה קלה למניעת עומס

        self.client_balances = balances
        return balances



    def start_background_tasks(self, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()

        loop.create_task(self._refresh_clients_loop())  # ✅ לולאת טעינת לקוחות
        loop.create_task(self._preload_balances_loop())  # ✅ אם אתה גם טוען יתרות ברקע

    async def _preload_balances_loop(self):
        """🔄 לולאת רקע לטעינת יתרות כל 3 דקות – יציבה ועמידה לשגיאות"""
        while True:
            try:
            #    logger.info("🚀 התחלת טעינת יתרות רקע")
                balances = await self.preload_balances(self.clients)
                
                if isinstance(balances, dict) and balances:
                    self.client_balances = balances
                    self.trade_operations.update_client_balances(balances)
                    #logger.info(f"✅ טעינת יתרות רקע הושלמה ({len(balances)} לקוחות)")
                else:
                    logger.warning("⚠️ לא התקבלו יתרות תקינות – לא עודכן")

            except Exception as e:
                logger.exception(f"❌ שגיאה כללית בלולאת טעינת יתרות ברקע: {e}")

            await asyncio.sleep(600)  # כל 3 דקות


    async def _refresh_clients_loop(self):
        while True:
            try:
                #logger.info("🔄 טוען את הלקוחות מחדש מהרקע...")
                self.clients = self.load_clients()
                self.trade_operations.update_clients(self.clients)
                #logger.info(f"✅ נטענו {len(self.clients)} לקוחות")
            except Exception as e:
                logger.error(f"❌ שגיאה בטעינת לקוחות מחדש: {e}")
            
            await asyncio.sleep(2000)  # ⏱️ כל 5 דקות
