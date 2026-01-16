import logging

# יצירת פורמט אחיד
log_format = "%(asctime)s - %(levelname)s - %(message)s"

# יצירת הלוגר הראשי
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 🔹 Handler 1 – לוג לקובץ
file_handler = logging.FileHandler("trades.log", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter(log_format))

# # 🔹 Handler 2 – לוג למסך (Render)
stream_handler = logging.StreamHandler()
stream_handler.setLevel(logging.INFO)
stream_handler.setFormatter(logging.Formatter(log_format))

# הוספה של שני ה־handlers ללוגר
logger.addHandler(file_handler)
logger.addHandler(stream_handler)
