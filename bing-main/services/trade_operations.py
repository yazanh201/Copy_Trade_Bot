import asyncio
from send_telegram_message import send_telegram_message
from core.logger import logger
from services.trade_math_utils import calculate_quantity_from_pct
from services.balance_manager import BalanceManager
import math




class TradeOperations:
    
    def __init__(self, master_api, clients, last_positions, client_positions, copied_trades, closed_trades,save_state_func):
        self.master_api = master_api
        self.clients = clients
        self.last_positions = last_positions
        self.client_positions = client_positions
        self.copied_trades = copied_trades
        self.closed_trades = closed_trades
        self.save_state = save_state_func
        self.balance_manager = BalanceManager()
        self.client_balances = {} 




    def update_clients(self, new_clients):
        self.clients = new_clients



    async def copy_trade(self, symbol, side, position_side, master_pct, price, leverage, tp, sl , isolated):
        #print(self.client_balances)
        try:
            await send_telegram_message(
                f"🚀 <b>ניסיון לפתוח עסקה:</b>\n📌 {symbol}\n📊  %{math.ceil(master_pct * 100)}\n📌 position_side: {position_side}\n"
                f"🔹 <b>Leverage:</b> {leverage or 'לא ידוע'}x\n🎯 <b>TP:</b> {tp or 'לא נקבע'}\n🛑 <b>SL:</b> {sl or 'לא נקבע'}"
            )

            batch_size = 10
            tasks = []

            for i in range(0, len(self.clients), batch_size):
                batch = self.clients[i:i + batch_size]
                client_names = [client["name"] for client in batch]
                #logger.info(f"📦 שולח קבוצה בגודל {len(batch)}: {client_names}")

                try:
                    task = asyncio.create_task(
                        self.execute_full_flow_for_batch(batch, symbol, side, position_side, master_pct, price, leverage, isolated)
                    )
                    tasks.append(task)
                    await asyncio.sleep(1.5)
                except Exception as e:
                    logger.error(f"❌ שגיאה בהכנת batch של לקוחות {client_names}: {e}")
                    await send_telegram_message(
                        f"❌ <b>שגיאה בעת הכנת קבוצה</b> של לקוחות {client_names}:\n{e}"
                    )

            # 🧠 איסוף כל המשימות, גם אם יש חריגות
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # ניתוח שגיאות
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    logger.error(f"❌ שגיאה ב־batch #{i+1}: {res}")
                    await send_telegram_message(f"❌ <b>שגיאה בביצוע קבוצה #{i+1}</b>: {res}")

            self.copied_trades[symbol] = True
            await self.save_state()

        except Exception as e:
            logger.critical(f"🚨 שגיאה קריטית ב־copy_trade ל־{symbol}: {e}")
            await send_telegram_message(f"🚨 <b>שגיאה קריטית</b> בפתיחת עסקה עבור {symbol}:\n{e}")


    async def close_trades(self, symbol):
        """✅ סגירת כל העסקאות לכל הלקוחות - בבת אחת, בקבוצות, בלי תורים"""

        if symbol in self.closed_trades:
            return

        await send_telegram_message(f"🔴 <b>מתבצעת סגירה של העסקה על:</b> {symbol}")

        async def process_client_close(client):
            client_name = client.get("name", "לא ידוע").lower()
            api = client["api"]

            try:
                if symbol not in self.client_positions.get(client_name, {}):
                    await send_telegram_message(
                        f"ℹ️ <b>אין עסקה פתוחה</b> על {symbol} אצל <b>{client_name}</b>"
                    )
                    return

                response = await api.close_all_positions(symbol)

                if isinstance(response, dict) and response.get("code") == 0:
                    await send_telegram_message(
                        f"✅ <b>העסקה על {symbol} נסגרה בהצלחה</b> עבור הלקוח {client_name}"
                    )

                    if client_name in self.client_positions and symbol in self.client_positions[client_name]:
                        del self.client_positions[client_name][symbol]
                        if not self.client_positions[client_name]:
                            del self.client_positions[client_name]

                    await self.save_state()

                    if symbol in self.last_positions:
                        del self.last_positions[symbol]

                else:
                    msg = response.get("msg", "שגיאה לא ידועה") if isinstance(response, dict) else str(response)
                    code = response.get("code", "לא ידוע") if isinstance(response, dict) else "לא ידוע"
                    logger.error(f"❌ שגיאה בסגירת עסקה ל-{client_name}: {msg} (קוד: {code})")
                    await send_telegram_message(
                        f"❌ <b>שגיאה בסגירת עסקה</b> ללקוח {client_name}:\n"
                        f"🔹 <b>סיבה:</b> {msg}\n🔹 <b>קוד:</b> {code}"
                    )

            except Exception as e:
                logger.exception(f"❌ חריגה לא צפויה בסגירת עסקה ל-{client_name}: {e}")
                await send_telegram_message(f"❌ <b>שגיאה כללית</b> בסגירת עסקה ללקוח {client_name}: {e}")

        # 🧠 Batching – חלוקה לקבוצות של 10 לקוחות עם השהייה
        batch_size = 7
        for i in range(0, len(self.clients), batch_size):
            batch = self.clients[i:i + batch_size]
            await asyncio.gather(*[process_client_close(client) for client in batch], return_exceptions=True)
            await asyncio.sleep(1)  # מנוחה של שנייה בין קבוצות

        self.closed_trades.discard(symbol)
        await self.save_state()



    async def close_partial_trades(self, symbol, master_closed_pct, side, position_side):
        """🔻 סוגר חלק מהעסקה לכל הלקוחות בקבוצות, במקביל, בלי תורים"""
        try:
            await send_telegram_message(
                f"🔴 <b>סגירה חלקית של עסקה:</b> {symbol}\n📉 אחוז סגירה: {master_closed_pct * 100:.2f}%"
            )

            batch_size = 7
            for i in range(0, len(self.clients), batch_size):
                batch = self.clients[i:i + batch_size]
                tasks = []

                for client in batch:
                    try:
                        client_name = client.get("name", "לא ידוע").lower()
                        client_qty = float(self.client_positions.get(client_name, {}).get(symbol, 0))
                        close_amount = client_qty * master_closed_pct

                        if close_amount < 0.000001:
                            continue

                        async def close_client(c=client, name=client_name, amount=close_amount):
                            try:
                                response = await c["api"].close_position_partially(symbol, amount, side, position_side)

                                if response.get("code") == 0:
                                    self.client_positions.setdefault(name, {})[symbol] -= amount
                                    if self.client_positions[name][symbol] <= 0:
                                        del self.client_positions[name][symbol]
                                        if not self.client_positions[name]:
                                            del self.client_positions[name]
                                    await self.save_state()

                                    remaining_pct = math.ceil((1 - master_closed_pct) * 100)
                                    await send_telegram_message(
                                        f"✅ <b>סגירה חלקית הושלמה</b> ללקוח <b>{name}</b>\n"
                                        f"📉 <b>אחוז נותר:</b> {remaining_pct}%"
                                    )
                                else:
                                    msg = response.get("msg", "לא ידועה")
                                    logger.warning(f"⚠️ שגיאה לוגית בסגירה חלקית ל-{name}: {msg}")
                                    await send_telegram_message(f"⚠️ <b>שגיאה לוגית</b> בסגירה חלקית ללקוח {name}: {msg}")
                            except Exception as e:
                                logger.exception(f"❌ חריגה בסגירה חלקית ל-{name}: {e}")
                                await send_telegram_message(f"❌ <b>שגיאה כללית</b> בסגירה חלקית ללקוח {name}: {e}")

                        tasks.append(close_client())

                    except Exception as e:
                        logger.error(f"❌ שגיאה בהכנת סגירה ללקוח {client.get('name', 'לא ידוע')}: {e}")
                        await send_telegram_message(f"❌ <b>שגיאה בהכנה</b> ללקוח {client.get('name', 'לא ידוע')}: {e}")

                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(1)  # 📉 מנוחה בין קבוצות

        except Exception as main_error:
            logger.critical(f"🚨 שגיאה קריטית ב־close_partial_trades: {main_error}")
            await send_telegram_message(f"🚨 <b>שגיאה קריטית</b> בסגירה חלקית: {main_error}")



    async def execute_full_flow_for_batch(self, batch, symbol, side, position_side, master_pct, price, leverage, isolated):
        async def process(client):
            client_name = client.get("name", "לא ידוע")
            api = client["api"]

            try:
                # 1. שליפת יתרה
                client_name = client_name.lower()  # הוסף שורה זו לפני השימוש בשם הלקוח
                balance_data = self.client_balances.get(client_name, {"available": 0})
                available_margin = float(balance_data.get("available", 0))
                if available_margin <= 0:
                    logger.warning(f"⚠️ יתרה לא מספיקה אצל {client_name} (יתרה: {available_margin})")
                    await send_telegram_message(
                        f"⚠️ <b>אזהרה:</b> ללקוח <b>{client_name}</b> אין יתרה מספיקה\n"
                        f"💰 <b>יתרה:</b> {available_margin}"
                    )
                    return

                # 2. חישוב כמות
                qty = calculate_quantity_from_pct(master_pct, available_margin, price, leverage)
                if qty <= 0:
                    logger.warning(f"⚠️ כמות לא חוקית אצל {client_name}")
                    return

                # 3. עדכון מינוף
                await api.set_leverage(symbol, leverage, position_side)

                # 4. עדכון מצב מרג'ין
                master_margin_mode = "ISOLATED" if isolated else "CROSS"
                await api.set_margin_mode(symbol, master_margin_mode)

                # בדיקה אם כבר קיימת עסקה
                existing_qty = self.client_positions.get(client_name, {}).get(symbol)
                #logger.info(f"🧪 בדיקת כמות קיימת ללקוח {client_name} על {symbol}: {existing_qty}")

                if existing_qty is not None and existing_qty > 0:
                    #logger.info(f"ℹ️ ללקוח {client_name} כבר קיימת עסקה פתוחה על {symbol}, דילוג.")
                    await send_telegram_message(
                        f"ℹ️ <b>העסקה לא נפתחה</b> ללקוח <b>{client_name}</b> כי כבר קיימת עסקה על {symbol}."
                    )
                    return

                # 5. פתיחת עסקה
                response = await api.open_trade(symbol, side, position_side, qty)

                if response and isinstance(response, dict):
                    if response.get("code") == 0:
                        self.client_positions.setdefault(client_name, {})[symbol] = qty
                        await self.save_state()
                        await send_telegram_message(
                            f"✅ <b>עסקה נפתחה</b> ללקוח <b>{client_name}</b>\n📌 סימבול: {symbol}"
                        )
                    else:
                        msg = response.get("msg", "שגיאה לא ידועה")
                        code = response.get("code", "לא ידוע")
                        logger.warning(f"⚠️ שגיאה בפתיחת עסקה אצל {client_name}: {msg} (קוד: {code})")
                        await send_telegram_message(
                            f"⚠️ <b>שגיאה</b> בפתיחת עסקה ללקוח <b>{client_name}</b>:\n"
                            f"📌 סימבול: {symbol}\n🧾 קוד: {code}\n🛑 הודעה: {msg}"
                        )
                else:
                    logger.error(f"❌ תגובה לא תקינה מה־API עבור {client_name}: {response}")
                    await send_telegram_message(
                        f"❌ <b>שגיאה לא צפויה</b> בתגובה מה־API אצל <b>{client_name}</b>"
                    )

            except Exception as e:
                logger.error(f"❌ שגיאה כללית בתהליך אצל {client_name}: {e}")
                await send_telegram_message(
                    f"❌ <b>שגיאה כללית</b> אצל <b>{client_name}</b>: {e}"
                )
                return e

        # 🚀 הרצת כל הלקוחות בקבוצה במקביל
        results = await asyncio.gather(*[process(client) for client in batch], return_exceptions=True)

        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"❌ חריגה בקבוצת לקוחות (index {i}): {res}")



    def update_client_balances(self, balances):
        self.client_balances = balances
        #logger.info(f"✅ Balances updated in TradeOperations: {self.client_balances}")
        #print("✅ Balances updated in TradeOperations:", self.client_balances)
