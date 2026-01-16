import bcrypt
from pymongo import MongoClient
from cryptography.fernet import Fernet
from core.config import MONGO_URI, DB_NAME, SECRET_KEY
from core.logger import logger

# יצירת אובייקט Fernet להצפנה/פענוח
fernet = Fernet(SECRET_KEY)

class SecureAPIManager:
    def __init__(self, uri=MONGO_URI, db_name=DB_NAME):
        try:
            self.client = MongoClient(uri)
            self.db = self.client[db_name]
          #  logger.info("✅ חיבור למסד הנתונים הצליח.")
        except Exception as e:
            logger.error(f"❌ שגיאה בחיבור ל־MongoDB: {e}")
            raise e


    def encrypt(self, value):
        try:
            if not isinstance(value, str):
                logger.warning("⚠️ ערך להצפנה אינו מחרוזת – מומר אוטומטית")
                value = str(value)

            encrypted = fernet.encrypt(value.encode()).decode()
            return encrypted

        except Exception as e:
            logger.exception(f"❌ שגיאה בהצפנת ערך: {e}")
            return None



    def decrypt(self, value):
        try:
            if not isinstance(value, str):
                logger.warning("⚠️ ערך לפענוח אינו מחרוזת – מומר אוטומטית")
                value = str(value)

            decrypted = fernet.decrypt(value.encode()).decode()
            return decrypted

        except Exception as e:
            logger.exception(f"❌ שגיאה בפענוח ערך: {e}")
            return None
        
    def add_client(self, name, api_key, secret_key):
        try:
            # ולידציה בסיסית
            if not name or not api_key or not secret_key:
                logger.warning("❌ ניסיון להוסיף לקוח עם שדות ריקים")
                return False

            if len(name) > 50:
                logger.warning(f"❌ שם הלקוח ארוך מדי: {name}")
                return False

            # בדיקה אם הלקוח כבר קיים
            existing = self.db.clients.find_one({"name": name})
            if existing:
                logger.warning(f"⚠️ לקוח בשם '{name}' כבר קיים במסד הנתונים")
                return False

            # הצפנה
            encrypted_api = self.encrypt(api_key)
            encrypted_secret = self.encrypt(secret_key)

            if not encrypted_api or not encrypted_secret:
                logger.error(f"❌ הצפנה נכשלה עבור לקוח '{name}'")
                return False

            # שמירה למסד
            self.db.clients.insert_one({
                "name": name,
                "api_key": encrypted_api,
                "secret_key": encrypted_secret
            })

            logger.info(f"✅ לקוח '{name}' נוסף בהצלחה למסד הנתונים")
            return True

        except Exception as e:
            logger.exception(f"❌ שגיאה בלתי צפויה בהוספת לקוח '{name}': {e}")
            return False


    def get_all_clients(self):
        clients = []
        for doc in self.db.clients.find({}):
            try:
                clients.append({
                    "_id": str(doc.get("_id")),
                    "name": doc.get("name", "לא ידוע"),
                    "api_key": self.decrypt(doc.get("api_key", "")),
                    "secret_key": self.decrypt(doc.get("secret_key", "")),
                    "subscription_start": doc.get("subscription_start", ""),
                    "subscription_end": doc.get("subscription_end", "")
                })
            except Exception as e:
                logger.warning(f"❌ שגיאה בפענוח לקוח {doc.get('name', 'לא ידוע')}: {e}")

       # logger.info(f"📋 הוחזרו {len(clients)} לקוחות כולל מפתחות מפוענחים")
        return clients

    def get_master(self):
        try:
            doc = self.db.MASTER.find_one()
            if not doc:
                logger.error("🔴 לא נמצא MASTER במסד הנתונים")
                raise Exception("🔴 לא נמצא MASTER במסד הנתונים")

            api_key = self.decrypt(doc.get("api_key", ""))
            secret_key = self.decrypt(doc.get("secret_key", ""))

            #logger.info("✅ מפתח MASTER נטען בהצלחה")
            return {
                "api_key": api_key,
                "secret_key": secret_key
            }

        except Exception as e:
            logger.exception(f"❌ שגיאה בעת שליפת MASTER: {e}")
            raise


    def validate_user(self, username, password):
        try:
            for user in self.db.users.find({}):
                try:
                    stored_username = self.decrypt(user.get("username", ""))
                    stored_password_hash = user.get("password", "").encode()

                    if stored_username == username and bcrypt.checkpw(password.encode(), stored_password_hash):
                        logger.info(f"🟢 אימות משתמש הצליח: {username}")
                        return True
                except Exception as inner_err:
                    logger.warning(f"⚠️ שגיאה באימות משתמש: {inner_err}")
                    continue

            logger.warning(f"🔴 אימות נכשל עבור משתמש: {username}")
            return False

        except Exception as outer_err:
            logger.error(f"❌ שגיאה כללית באימות משתמש: {outer_err}")
            return False

