from services.secure_api_manager import SecureAPIManager

def load_apis_from_db():
    manager = SecureAPIManager()
    
    # שליפת master מוצפן + פענוח
    master = manager.get_master()

    # שליפת כל הלקוחות ופענוח
    clients = manager.get_all_clients()

    return {
        "master": master,
        "clients": clients
    }
