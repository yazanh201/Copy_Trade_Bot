import os

# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

if not MONGO_URI or not DB_NAME:
    raise Exception("❌ Environment variables MONGO_URI or DB_NAME are missing!")

# Load encryption key directly from environment variable
SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise Exception("❌ SECRET_KEY environment variable is missing!")

# If needed as bytes (e.g., for Fernet)
SECRET_KEY = SECRET_KEY.encode()
