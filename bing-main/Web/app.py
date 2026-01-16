import os
import sys
import asyncio
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask, render_template, request, redirect, url_for, session, flash
from services.secure_api_manager import SecureAPIManager
from bson.objectid import ObjectId 
from services.trade_manager import TradeManager  # ודא שזה נמצא למעלה בקובץ
from markupsafe import escape  # נשתמש כדי למנוע XSS
from datetime import datetime, timedelta


#import logging
#logging.getLogger('werkzeug').disabled = True


app = Flask(__name__)
app.secret_key = os.urandom(24)  # 🔐 לשמירת session בצורה בטוחה

manager = SecureAPIManager()


@app.route("/dashboard")
def dashboard():
    if not session.get("user"):
        return redirect(url_for("login"))

    try:
        clients = manager.get_all_clients()
    except Exception as e:
        clients = []
        flash(f"⚠️ שגיאה בטעינת לקוחות: {str(e)}", "warning")

    try:
        from services.trade_state_mongo import TradeStateMongoManager
        mongo_state = TradeStateMongoManager()
        state = asyncio.run(mongo_state.load_state())
        master_positions = state.get("last_positions", {})
    except Exception as e:
        master_positions = {}
        flash(f"⚠️ שגיאה בטעינת מצב עסקאות: {str(e)}", "warning")

    return render_template("dashboard.html", master_positions=master_positions)



@app.route("/clients")
def clients():
    if "user" not in session:
        return redirect(url_for("login"))

    search_query = request.args.get("search", "").strip().lower()
    show_expired = request.args.get("expired", "") == "1"

    all_clients = manager.get_all_clients()

    # סינון לפי חיפוש
    if search_query:
        all_clients = [c for c in all_clients if search_query in c["name"].lower()]

    # סינון לפי תאריך סיום
    if show_expired:
        today = datetime.today().date()
        def is_expired(client):
            try:
                end_date = datetime.strptime(client.get("subscription_end", ""), "%Y-%m-%d").date()
                return (today - end_date).days >= 0
            except:
                return False
        all_clients = [c for c in all_clients if is_expired(c)]

    return render_template("clients.html", clients=all_clients, search_query=search_query, show_expired=show_expired)


@app.route("/add-client", methods=["GET", "POST"])
def add_client():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        api_key = request.form.get("api_key", "").strip()
        secret_key = request.form.get("secret_key", "").strip()

        # ניקוי קלט (מניעת XSS)
        name = escape(name)

        # ולידציה בסיסית
        if not name or not api_key or not secret_key:
            flash("❌ יש למלא את כל השדות", "danger")
            return redirect(url_for("add_client"))

        if len(name) > 50:
            flash("❌ שם הלקוח ארוך מדי (מקסימום 50 תווים)", "danger")
            return redirect(url_for("add_client"))

        # בדיקה אם כבר קיים לקוח עם אותו שם
        existing = manager.db.clients.find_one({"name": name})
        if existing:
            flash("⚠️ לקוח עם שם זה כבר קיים", "warning")
            return redirect(url_for("add_client"))

        try:
            manager.add_client(name, api_key, secret_key)
            flash("✅ לקוח נוסף בהצלחה!", "success")
        except Exception as e:
            flash(f"❌ שגיאה בהוספת לקוח: {str(e)}", "danger")

        return redirect(url_for("dashboard"))

    return render_template("add_client.html")


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        # ניקוי בסיסי למניעת XSS
        username = escape(username)

        # ולידציה בסיסית
        if not username or not password:
            flash("❌ יש למלא גם שם משתמש וגם סיסמה", "danger")
            return render_template("login.html")

        if manager.validate_user(username, password):
            session["user"] = username
            return redirect(url_for("dashboard"))
        else:
            flash("❌ שם משתמש או סיסמה שגויים", "danger")

    return render_template("login.html")


# ✅ התנתקות
@app.route("/logout")
def logout():
    session.clear()
    flash("📤 התנתקת בהצלחה", "info")
    return redirect(url_for("login"))


# ✅ מחיקת לקוח
@app.route("/delete-client/<client_id>", methods=["POST"])
def delete_client(client_id):
    if "user" not in session:
        return redirect(url_for("login"))

    # בדיקה האם ה-ID תקין
    try:
        object_id = ObjectId(client_id)
    except Exception:
        flash("❌ מזהה לקוח לא תקין", "danger")
        return redirect(url_for("clients"))

    # נסיון למחוק מהמסד
    try:
        result = manager.db.clients.delete_one({"_id": object_id})
        if result.deleted_count == 0:
            flash("⚠️ לקוח לא נמצא או כבר נמחק", "warning")
        else:
            flash("🗑️ הלקוח נמחק בהצלחה", "success")
    except Exception as e:
        flash(f"❌ שגיאה במחיקת הלקוח: {str(e)}", "danger")

    return redirect(url_for("clients"))


# ✅ דף עריכה
from markupsafe import escape

@app.route("/edit-client/<client_id>", methods=["GET", "POST"])
def edit_client(client_id):
    if "user" not in session:
        return redirect(url_for("login"))

    # בדיקת תקינות ObjectId
    try:
        object_id = ObjectId(client_id)
    except Exception:
        flash("❌ מזהה לקוח לא תקין", "danger")
        return redirect(url_for("clients"))

    # שליפת מסמך
    client_doc = manager.db.clients.find_one({"_id": object_id})
    if not client_doc:
        flash("❌ לקוח לא נמצא", "danger")
        return redirect(url_for("clients"))

    if request.method == "POST":
        name = escape(request.form.get("name", "").strip())
        api_key = request.form.get("api_key", "").strip()
        secret_key = request.form.get("secret_key", "").strip()
        subscription_start = request.form.get("subscription_start", "").strip()
        subscription_end = request.form.get("subscription_end", "").strip()

        # ולידציה בסיסית
        if not name or not api_key or not secret_key:
            flash("❌ כל השדות נדרשים", "danger")
            return redirect(url_for("edit_client", client_id=client_id))

        if len(name) > 50:
            flash("❌ שם הלקוח ארוך מדי", "danger")
            return redirect(url_for("edit_client", client_id=client_id))

        try:
            encrypted_api = manager.encrypt(api_key)
            encrypted_secret = manager.encrypt(secret_key)

            result = manager.db.clients.update_one(
                {"_id": object_id},
                {"$set": {
                    "name": name,
                    "api_key": encrypted_api,
                    "secret_key": encrypted_secret,
                    "subscription_start": subscription_start,
                    "subscription_end": subscription_end
                }}
            )

            if result.matched_count == 0:
                flash("⚠️ לקוח לא עודכן", "warning")
            else:
                flash("✅ פרטי הלקוח עודכנו בהצלחה", "success")
        except Exception as e:
            flash(f"❌ שגיאה בעדכון הלקוח: {str(e)}", "danger")

        return redirect(url_for("clients"))

    # הצגת פרטי הלקוח – בצורה בטוחה
    decrypted_client = {
        "name": client_doc["name"],
        "api_key": manager.decrypt(client_doc["api_key"]),
        "secret_key": manager.decrypt(client_doc["secret_key"]),
        "subscription_start": client_doc.get("subscription_start", ""),
        "subscription_end": client_doc.get("subscription_end", "")
    }

    return render_template("edit_client.html", client=decrypted_client, client_id=client_id)


@app.route("/dashboard/table")
def dashboard_table():
    if not session.get("user"):
        return "", 403

    try:
        from services.trade_state_mongo import TradeStateMongoManager
        mongo_state = TradeStateMongoManager()
        state = asyncio.run(mongo_state.load_state())
        master_positions = state.get("last_positions", {})
    except Exception as e:
        master_positions = {}
        # אפשר גם לשקול להחזיר הודעה או JSON ריק
        print(f"⚠️ שגיאה בטעינת מצב המאסטר: {e}")

    return render_template("master_table.html", master_positions=master_positions)



if __name__ == "__main__":
    app.run(debug=True)


