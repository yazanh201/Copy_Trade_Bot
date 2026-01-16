import time
import hmac
import hashlib

class APIUtils:
    """ מחלקת עזר לניהול חתימות ופרמטרים """
    
    @staticmethod
    def get_sign(secret_key, payload):
        """יוצר חתימה HMAC-SHA256 עבור אימות API"""
        return hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), digestmod=hashlib.sha256).hexdigest()

    @staticmethod
    def parse_param(params_map):
        """ממיר מילון פרמטרים למחרוזת URL עם חותמת זמן"""
        params_map["timestamp"] = str(int(time.time() * 1000))
        sorted_keys = sorted(params_map)
        return "&".join([f"{key}={params_map[key]}" for key in sorted_keys])
