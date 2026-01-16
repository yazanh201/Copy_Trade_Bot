import logging

logger = logging.getLogger(__name__)


def calculate_master_pct_by_available_margin(position_value, leverage, available_margin) -> float:
    """
    מחשבת את אחוז ההשקעה של המאסטר מתוך:
    - position_value (כולל מינוף)
    - leverage
    - available_margin (יתרה זמינה)

    מחזירה ערך בין 0 ל-1
    """
    try:
        if leverage <= 0 or position_value <= 0:
            return 0.0

        real_invested_amount = position_value / leverage
        total_balance = available_margin + real_invested_amount

        if total_balance == 0:
            return 0.0

        return real_invested_amount / total_balance

    except Exception as e:
        logger.error(f"❌ שגיאה בחישוב master_pct (טהור): {e}")
        return 0.0


def calculate_quantity_from_pct(master_pct, client_balance, price, leverage, precision=8):
    """
    מחשב כמות פתיחה ללקוח לפי אחוז השקעה של המאסטר,
    יתרת הלקוח (available), מחיר המטבע, ומינוף.
    """
    try:
        if price <= 0 or client_balance <= 0 or leverage <= 0 or master_pct <= 0:
            return 0.0

        # כמה דולר להשקיע בפועל
        client_usdt_to_invest = client_balance * master_pct

        # כמה תהיה שווה הפוזיציה עם המינוף
        position_value = client_usdt_to_invest * leverage

        # כמות המטבע
        quantity = position_value / price
        return round(quantity, precision)

    except Exception as e:
        logger.error(f"❌ שגיאה בחישוב כמות ללקוח: {e}")
        return 0.0


async def get_clients_available_balances(clients, asset="USDT"):
    """
    מחזיר מילון עם יתרות זמינות של כל הלקוחות לפי asset
    { client_name: availableMargin }
    """
    balances = {}
    for client in clients:
        name = client["name"]
        api = client["api"]
        try:
            data = await api.get_balance_details(asset)
            balances[name] = float(data.get("available", 0))
        except Exception as e:
            logger.warning(f"⚠️ שגיאה בשליפת יתרה זמינה עבור {name}: {e}")
            balances[name] = 0.0
    return balances
