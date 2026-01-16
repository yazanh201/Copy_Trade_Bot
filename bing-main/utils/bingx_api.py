import asyncio
import aiohttp
import time
import hmac
import hashlib
from utils.apiutils import APIUtils
from send_telegram_message import send_telegram_message
from core.logger import logger



MAX_RETRIES = 3
RETRY_DELAY = 1  # שניות

class BingXAPI:
    APIURL = "https://open-api.bingx.com"

    def __init__(self, api_key, secret_key, session=None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.session = session  # יכול להיות חיצוני
        self._session_owner = session is None  # נדע אם אנחנו צריכים לסגור אותו
        self.rate_limit_wait = 1
        self.cache = {}
        
    async def start_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
            self._session_owner = True
            #logger.info("🔵 חיבור API נפתח")

    async def close_session(self):
        if self.session and self._session_owner:
            await self.session.close()
            #logger.info("🔴 חיבור API נסגר")
        self.session = None


    async def _send_request(self, method, path, params_map, max_retries=5):
        """🚀 שליחת בקשת API עם ניהול Rate Limit, טיפול בשגיאות רשת, ותגובות לא תקינות"""
        await self.start_session()  # יצירת session אם לא קיים
    
        # ✅ הכנת הפרמטרים וחתימה
        params_map["timestamp"] = str(int(time.time() * 1000))
        params_str = APIUtils.parse_param(params_map)
        signature = hmac.new(self.secret_key.encode(), params_str.encode(), hashlib.sha256).hexdigest()
    
        url = f"{self.APIURL}{path}?{params_str}&signature={signature}"
        headers = {"X-BX-APIKEY": self.api_key}
    
        for attempt in range(1, max_retries + 1):
            try:
                async with self.session.request(method, url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    try:
                        response_data = await response.json()
                    except Exception:
                        text = await response.text()
                        logger.error(f"❌ לא ניתן לפענח JSON ({response.status}): {text}")
                        return {"code": -1, "msg": "Invalid JSON response"}
    
                    if response.status == 429:
                        wait_time = min(self.rate_limit_wait * 2, 10)  # מגביל המתנה ל־10 שניות
                        logger.warning(f"🚨 Rate Limit! ניסיון {attempt}/{max_retries}. מחכה {wait_time} שניות...")
                        self.rate_limit_wait = wait_time
                        await asyncio.sleep(wait_time)
                        continue
    
                    if response.status == 200 and response_data.get("code") == 0:
                        #logger.info(f"✅ בקשת API הצליחה: {method} {path}")
                        self.rate_limit_wait = 1  # איפוס המתנה אחרי הצלחה
                        return response_data
    
                    # 🔴 אם התגובה נכונה אך הקוד לא 0 – שגיאה לוגית
                    logger.warning(f"⚠️ API Error ({response.status}): {response_data}")
                    return response_data
    
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.error(f"❌ שגיאת רשת (ניסיון {attempt}/{max_retries}): {e}")
                await asyncio.sleep(2)
    
        logger.critical("❌ כל הניסיונות נכשלו – לא ניתן להתחבר ל-API")
        return {"code": -1, "msg": "שגיאת חיבור API לאחר מספר ניסיונות"}

    
    async def get_positions(self):
        """✅ שליפת כל הפוזיציות הפתוחות עם טיפול שגיאות חכם וריטריי"""
        endpoint = "/openApi/swap/v2/user/positions"
        params = {"recvWindow": "5000"}
    
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._send_request("GET", endpoint, params)
    
                if response is None:
                    raise ValueError("לא התקבלה תשובה מהשרת (response=None)")
    
                if response.get("code") != 0 or "data" not in response:
                    logger.warning(f"⚠️ ניסיון {attempt}/{MAX_RETRIES} - קיבלנו קוד שגוי או נתונים חסרים מה-API: {response}")
                    await asyncio.sleep(RETRY_DELAY)
                    continue
    
                return response  # ✅ הצלחה
    
            except (aiohttp.ClientError, asyncio.TimeoutError) as net_err:
                logger.error(f"❌ ניסיון {attempt}/{MAX_RETRIES} - שגיאת רשת: {net_err}")
            except Exception as e:
                logger.error(f"❌ ניסיון {attempt}/{MAX_RETRIES} - שגיאה כללית ב-get_positions: {e}")
    
            await asyncio.sleep(RETRY_DELAY)
    
        logger.error("🚫 נכשל בשליפת פוזיציות לאחר כל ניסיונות הריטריי, מחזיר רשימה ריקה")
        return {"code": -1, "data": []}  # ✅ תמיד מחזיר מבנה תקני

    async def open_trade(self, symbol, side, position_side, qty):
        """🚀 פתיחת עסקה עם טיפול שגיאות חכם והחזרת תגובה תקנית"""
        await self.start_session()

        try:
            qty_str = "{:.8f}".format(qty)
            side = "SELL" if position_side.upper() == "SHORT" else "BUY"

            params = {
                "symbol": symbol,
                "side": side,
                "positionSide": position_side,
                "type": "MARKET",
                "quantity": qty_str,
                "timestamp": str(int(time.time() * 1000))
            }

            #logger.info(f"🚀 ניסיון לפתוח עסקה: {symbol} ({side}), Position Side: {position_side}, כמות: {qty_str}")

            response = await self._send_request("POST", "/openApi/swap/v2/trade/order", params)

            # אם אין תגובה תקפה בכלל
            if response is None:
                logger.error(f"❌ שגיאה: לא התקבלה תגובה מהשרת בעת פתיחת עסקה: {symbol}")
                return {"code": -1, "msg": "No response from server"}

            if response.get("code") == 0:
                #logger.info(f"✅ עסקה נפתחה בהצלחה: {symbol} ({side}) כמות: {qty_str}")
                return response

            # טיפול במקרה של תגובה עם קוד שגיאה
            error_msg = response.get("msg", "שגיאה לא ידועה")
            error_code = response.get("code", "לא ידוע")

            logger.error(f"❌ שגיאה בפתיחת עסקה: {symbol} ({side}) - {error_msg} (קוד: {error_code})")
            return response

        except Exception as e:
            logger.exception(f"❌ חריגה לא צפויה בפתיחת עסקה עבור {symbol}: {e}")
            return {"code": -999, "msg": str(e)}



    async def close_all_positions(self, symbol):
        """✅ סגירת כל העסקאות הפתוחות עם טיפול שגיאות חכם ולוגים ברורים"""
        #logger.info(f"🔴 ניסיון לסגור את כל העסקאות של {symbol}")
        try:
            response = await self._send_request(
                "POST",
                "/openApi/swap/v2/trade/closeAllPositions",
                {"symbol": symbol}
            )

            if response is None:
                logger.error(f"❌ לא התקבלה תגובה מהשרת בעת סגירת כל העסקאות של {symbol}")
                return {"code": -1, "msg": "No response from server"}

            if response.get("code") == 0:
                #logger.info(f"✅ כל העסקאות של {symbol} נסגרו בהצלחה")
                return response

            error_msg = response.get("msg", "שגיאה לא ידועה")
            error_code = response.get("code", "לא ידוע")
            logger.error(f"❌ שגיאה בסגירת עסקאות של {symbol}: {error_msg} (קוד: {error_code})")
            return response

        except Exception as e:
            logger.exception(f"❌ חריגה לא צפויה בעת ניסיון לסגור את כל העסקאות של {symbol}: {e}")
            return {"code": -999, "msg": str(e)}
   
     
    async def close_position_partially(self, symbol, qty, side, position_side):
        """🔻 סוגר חלק מהעסקה בצורה בטוחה עם טיפול בשגיאות ולוגים ברורים"""
        #logger.info(f"🔴 ניסיון לסגור חלק מהעסקה {symbol}, כמות: {qty}")

        try:
            close_side = "SELL" if position_side.upper() == "LONG" else "BUY"

            params = {
                "symbol": symbol,
                "side": close_side,
                "positionSide": position_side,
                "quantity": "{:.8f}".format(qty),
                "type": "MARKET",
                "timestamp": str(int(time.time() * 1000)),
                "recvWindow": "10000"
            }

            response = await self._send_request("POST", "/openApi/swap/v2/trade/order", params)

            if response is None:
                logger.error(f"❌ לא התקבלה תגובה מהשרת בסגירה חלקית של {symbol}")
                return {"code": -1, "msg": "No response from server"}

            if response.get("code") == 0:
                #logger.info(f"✅ סגירה חלקית הושלמה עבור {symbol}, כמות: {qty}")
                pass
            else:
                error_msg = response.get("msg", "שגיאה לא ידועה")
                error_code = response.get("code", "לא ידוע")
                logger.warning(f"⚠️ שגיאה בסגירה חלקית של {symbol}: {error_msg} (קוד: {error_code})")

            return response

        except Exception as e:
            logger.exception(f"❌ חריגה לא צפויה בעת סגירה חלקית של {symbol}: {e}")
            return {"code": -999, "msg": str(e)}



    async def set_leverage(self, symbol, leverage, position_side):
        """🔄 מעדכן את המינוף (Leverage) למשתמש עם טיפול בשגיאות"""
        #logger.info(f"🔄 ניסיון לעדכן מינוף עבור {symbol} ל-{leverage}x (Position Side: {position_side})")

        try:
            params = {
                "symbol": symbol,
                "leverage": str(leverage),
                "side": position_side,  # לדוגמה: "LONG" או "SHORT"
                "timestamp": str(int(time.time() * 1000))
            }

            response = await self._send_request("POST", "/openApi/swap/v2/trade/leverage", params)

            if response is None:
                logger.error(f"❌ לא התקבלה תגובה מהשרת בעדכון מינוף של {symbol}")
                return {"code": -1, "msg": "No response from server"}

            if response.get("code") == 0:
                #logger.info(f"✅ מינוף עודכן בהצלחה עבור {symbol} ל-{leverage}x")
                pass
            else:
                error_msg = response.get("msg", "שגיאה לא ידועה")
                error_code = response.get("code", "לא ידוע")
                logger.warning(f"⚠️ שגיאה בעדכון מינוף עבור {symbol}: {error_msg} (קוד: {error_code})")

            return response

        except Exception as e:
            logger.exception(f"❌ חריגה לא צפויה בעדכון מינוף עבור {symbol}: {e}")
            return {"code": -999, "msg": str(e)}


    async def set_margin_mode(self, symbol, margin_mode):
        """🔄 מעדכן את מצב ה-Margin (CROSSED / ISOLATED) עם ניהול שגיאות חכם"""
        try:
            margin_type = "CROSSED" if margin_mode.upper() == "CROSS" else "ISOLATED"
            #logger.info(f"🔄 ניסיון לעדכן Margin Mode עבור {symbol} ל-{margin_type}")

            params = {
                "symbol": symbol,
                "marginType": margin_type,
                "recvWindow": "60000",
                "timestamp": str(int(time.time() * 1000))
            }

            response = await self._send_request("POST", "/openApi/swap/v2/trade/marginType", params)

            if response is None:
                logger.error(f"⚠️ לא התקבלה תגובה מהשרת בעדכון Margin Mode עבור {symbol}")
                return {"code": -1, "msg": "No response from server"}

            if response.get("code") == 0:
                #logger.info(f"✅ מצב Margin עודכן בהצלחה עבור {symbol} ({margin_type})")
                pass
            else:
                error_msg = response.get("msg", "שגיאה לא ידועה")
                error_code = response.get("code", "לא ידוע")
                logger.warning(f"⚠️ שגיאה בעדכון Margin Mode עבור {symbol}: {error_msg} (קוד: {error_code})")

            return response

        except Exception as e:
            logger.exception(f"❌ חריגה לא צפויה בעדכון Margin Mode עבור {symbol}: {e}")
            return {"code": -999, "msg": str(e)}

        
        
    async def get_trade_parameters(self, symbol):
        """🔍 שליפת נתוני TP, SL ו-Leverage עבור סימבול עם טיפול בשגיאות"""
        try:
            #logger.info(f"📌 שליפת נתוני מסחר (Leverage, TP, SL) עבור {symbol}...")

            response = await self._send_request("GET", "/openApi/swap/v2/trade/openOrders", {"symbol": symbol})

            if not response or response.get("code") != 0 or "data" not in response:
                logger.warning(f"⚠️ לא ניתן לקבל נתוני Open Orders עבור {symbol}, מחזיר ערכים ריקים.")
                return None, None, None

            orders = response["data"].get("orders", [])
            leverage = None
            take_profit = None
            stop_loss = None

            for order in orders:
                if order.get("symbol") != symbol:
                    continue

                # שליפת מינוף רק אם טרם הוגדר
                if leverage is None and "leverage" in order:
                    leverage = order["leverage"].replace("X", "")

                if order.get("type") == "TAKE_PROFIT_MARKET":
                    take_profit = order.get("stopPrice", "לא נקבע")

                if order.get("type") == "STOP_MARKET":
                    stop_loss = order.get("stopPrice", "לא נקבע")

            #logger.info(f"✅ {symbol}: Leverage: {leverage}x, TP: {take_profit}, SL: {stop_loss}")
            return leverage, take_profit, stop_loss

        except Exception as e:
            logger.exception(f"❌ שגיאה בשליפת פרמטרים עבור {symbol}: {e}")
            return None, None, None


    async def get_balance_details(self, asset="USDT"):
        """
        מחזיר את פרטי היתרה (equity, availableMargin, usedMargin, balance) כולל ריטריי ויציבות
        """
        endpoint = "/openApi/swap/v3/user/balance"
        params = {"recvWindow": "5000"}

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._send_request("GET", endpoint, params)
                if response.get("code") != 0 or "data" not in response:
                    logger.warning(f"⚠️ ניסיון {attempt}/{MAX_RETRIES} - כשל ב-get_balance_details: {response}")
                    await asyncio.sleep(RETRY_DELAY)
                    continue

                for item in response["data"]:
                    if item.get("asset") == asset:
                        return {
                            "available": float(item.get("availableMargin", 0)),
                            "equity": float(item.get("equity", 0)),
                            "used": float(item.get("usedMargin", 0)),
                            "balance": float(item.get("balance", 0))
                        }

                logger.warning(f"🔍 לא נמצאה יתרת {asset}")
                return {}

            except Exception as e:
                logger.error(f"❌ שגיאה ב-get_balance_details ניסיון {attempt}/{MAX_RETRIES}: {e}")

            await asyncio.sleep(RETRY_DELAY)

        logger.error("🚫 נכשל בשליפת balance details לאחר מספר ניסיונות")
        return {}

