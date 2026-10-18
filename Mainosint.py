import logging
import asyncio
import uuid
from datetime import datetime, timedelta, date
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeAllGroupChats, ReplyParameters
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.error import Forbidden
from telegram.request import HTTPXRequest
import aiohttp
from pymongo import MongoClient

# ================= SPEED: LOGGING OFF =================
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.request").setLevel(logging.WARNING)
logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

# ================= CONFIG =================
BOT_TOKEN = "8604072881:AAGMgKxlMwSWoLkd4ys6LRAQ-a47Jg6DrMo"
OWNER_ID = 8544308334
MONGO_URI = "mongodb+srv://mailprimesatyam_db_user:KHieavEmwVOBG0Hv@tg-bot-cluster.y7h9ddx.mongodb.net/?appName=tg-bot-cluster"

DEFAULT_WELCOME_BONUS = 5
DAILY_BONUS = 3
REFER_REWARD = 10

# ================= FAST DB CONNECTION =================
client = MongoClient(MONGO_URI, maxPoolSize=100, minPoolSize=20,
    serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
    socketTimeoutMS=10000, retryWrites=True)
db = client["telegram_bot"]
users_col = db["users"]
redeem_col = db["redeem_codes"]
settings_col = db["settings"]

users_col.create_index("user_id", unique=True)
redeem_col.create_index("code", unique=True)

# ================= APIs =================
API_NUMBER = "https://anurixx-gift-number.vercel.app/api?num={term}"
API_AADHAR = "https://api.osintxc.com/aadhaar?value={term}&key=DADDY"
API_VEHICLE = "https://api.sarkariallupdates.com/api?=vehicle_full&key=30day&xr={term}"
API_TG = "https://anshapi.pages.dev/api/tg?type=tg_num&query={term}"

# ================= CACHES (FAST LOGIC) =================
SETTINGS_CACHE = {}
USER_CACHE = {}
ADMIN_CACHE = set()
API_CACHE = {}
JOIN_CACHE = {}

SETTINGS_TTL = 60
API_CACHE_TTL = 300
JOIN_TTL = 30

def get_setting(key, default=None):
    cached = SETTINGS_CACHE.get(key)
    if cached:
        val, ts = cached
        if (datetime.now() - ts).total_seconds() < SETTINGS_TTL:
            return val
    d = settings_col.find_one({"key": key})
    if not d:
        settings_col.insert_one({"key": key, "value": default})
        SETTINGS_CACHE[key] = (default, datetime.now())
        return default
    SETTINGS_CACHE[key] = (d["value"], datetime.now())
    return d["value"]

def set_setting(key, val):
    settings_col.update_one({"key": key}, {"$set": {"value": val}}, upsert=True)
    SETTINGS_CACHE[key] = (val, datetime.now())

def get_bot_credit(): return get_setting("bot_credit", "@hexasuport")
def get_welcome_bonus(): return get_setting("welcome_bonus", DEFAULT_WELCOME_BONUS)
def get_daily_bonus(): return get_setting("daily_bonus", DAILY_BONUS)
def get_force_enabled(): return get_setting("force_enabled", False)
def get_maintenance_global(): return get_setting("maintenance_global", False)
def get_maint_features(): return get_setting("maintenance_features", []) or []
def is_feature_maint(f): return f in get_maint_features()
def load_channels(): return get_setting("force_channels", []) or []
def save_channels(c): set_setting("force_channels", c)

AADHAR_PAGINATION = {}

FEATURES = [
    ("number", "📱 Number Info"), ("aadhar", "🆔 Aadhar Info"),
    ("vehicle", "🚗 Vehicle to Num"), ("tg", "🆔 TG ID Info"),
    ("refer", "🎁 Refer & Earn"), ("redeem", "🎫 Redeem Code"),
    ("profile", "👤 My Profile"),
]

_api_session = None
async def get_session():
    global _api_session
    if _api_session is None or _api_session.closed:
        connector = aiohttp.TCPConnector(limit=100, limit_per_host=20,
            ttl_dns_cache=600, use_dns_cache=True,
            keepalive_timeout=30, enable_cleanup_closed=True)
        _api_session = aiohttp.ClientSession(connector=connector,
            timeout=aiohttp.ClientTimeout(total=20, connect=5, sock_read=15),
            headers={"User-Agent": "Mozilla/5.0"})
    return _api_session

# ================= FONTS =================
def bold(text):
    res = []
    for c in str(text):
        if 'A' <= c <= 'Z': res.append(chr(0x1D5D4 + (ord(c) - ord('A'))))
        elif 'a' <= c <= 'z': res.append(chr(0x1D5EE + (ord(c) - ord('a'))))
        elif '0' <= c <= '9': res.append(chr(0x1D7EC + (ord(c) - ord('0'))))
        else: res.append(c)
    return ''.join(res)

def small_caps(text):
    m = {'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
         'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴩ','q':'q','r':'ʀ',
         's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
         'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
         'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴩ','Q':'Q','R':'ʀ',
         'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'X','Y':'ʏ','Z':'ᴢ'}
    return ''.join(m.get(c, c) for c in str(text))

def no_data_msg(subject="number"):
    subjects = {"number": "ᴛʜɪꜱ ɴᴜᴍʙᴇʀ", "aadhar": "ᴛʜɪꜱ ᴀᴀᴅʜᴀᴀʀ ɴᴜᴍʙᴇʀ",
                "vehicle": "ᴛʜɪꜱ ᴠᴇʜɪᴄʟᴇ ɴᴜᴍʙᴇʀ", "tg": "ᴛʜɪꜱ ᴜꜱᴇʀ ɪᴅ"}
    subj = subjects.get(subject, "ᴛʜɪꜱ")
    return f"❌ {small_caps('no information found for ' + subj + '!')}\n\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"

def not_enough_msg():
    return f"❌ <b>{small_caps('not enough credits')}</b>\n\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"

def rp(msg_id):
    return ReplyParameters(message_id=msg_id)

# ================= HELPERS =================
def is_admin(uid):
    if uid == OWNER_ID: return True
    return uid in ADMIN_CACHE

def get_user(uid):
    if uid in USER_CACHE:
        d = USER_CACHE[uid]
    else:
        d = users_col.find_one({"user_id": uid}, {"user_id": 1, "credits": 1, "referrals": 1,
            "credits_expiry": 1, "premium_until": 1, "suspended": 1, "blocked": 1, "last_daily": 1})
        if not d:
            users_col.insert_one({"user_id": uid, "credits": get_welcome_bonus(), "referrals": 0,
                "joined_date": datetime.now().isoformat(), "credits_expiry": None,
                "premium_until": None, "blocked": False, "suspended": False, "last_daily": None})
            d = users_col.find_one({"user_id": uid})
        USER_CACHE[uid] = d
        
    if d.get("credits_expiry"):
        try:
            if datetime.now() > datetime.fromisoformat(d["credits_expiry"]):
                users_col.update_one({"user_id": uid}, {"$set": {"credits": 0, "credits_expiry": None}})
                d["credits"] = 0; d["credits_expiry"] = None
                USER_CACHE[uid] = d
        except: pass
    if d.get("premium_until"):
        try:
            if datetime.now() > datetime.fromisoformat(d["premium_until"]):
                users_col.update_one({"user_id": uid}, {"$set": {"premium_until": None}})
                d["premium_until"] = None
                USER_CACHE[uid] = d
        except: pass
    return d

def is_suspended(uid):
    if is_admin(uid): return False
    d = get_user(uid)
    return d and d.get("suspended", False)

def has_unlimited(uid):
    d = get_user(uid)
    if not d.get("premium_until"): return False
    try: return datetime.now() < datetime.fromisoformat(d["premium_until"])
    except: return False

def add_credits(uid, amount, days=0):
    update = {"$inc": {"credits": amount}}
    if days > 0:
        update["$set"] = {"credits_expiry": (datetime.now() + timedelta(days=days)).isoformat()}
    users_col.update_one({"user_id": uid}, update, upsert=True)
    if uid in USER_CACHE:
        USER_CACHE[uid]["credits"] += amount
        if days > 0: USER_CACHE[uid]["credits_expiry"] = (datetime.now() + timedelta(days=days)).isoformat()

def refund_credit(uid):
    if has_unlimited(uid): return
    users_col.update_one({"user_id": uid}, {"$inc": {"credits": 1}})
    if uid in USER_CACHE: USER_CACHE[uid]["credits"] += 1

def claim_daily(uid):
    d = users_col.find_one({"user_id": uid}, {"last_daily": 1})
    today = date.today().isoformat()
    if not d: return False
    if d.get("last_daily") == today: return False
    users_col.update_one({"user_id": uid}, {"$inc": {"credits": get_daily_bonus()}, "$set": {"last_daily": today}})
    if uid in USER_CACHE:
        USER_CACHE[uid]["credits"] += get_daily_bonus()
        USER_CACHE[uid]["last_daily"] = today
    return True

def get_mongo_stats():
    try:
        stats = db.command("dbstats")
        storage_size = stats.get("storageSize", 0) / (1024 * 1024)
        FREE_LIMIT = 512
        used_pct = (storage_size / FREE_LIMIT) * 100 if FREE_LIMIT else 0
        return {"storage_size": round(storage_size, 2), "free_limit": FREE_LIMIT,
                "free_mb": round(FREE_LIMIT - storage_size, 2), "used_pct": round(used_pct, 2),
                "objects": stats.get("objects", 0), "collections": stats.get("collections", 0)}
    except: return {"storage_size": 0, "free_limit": 512, "free_mb": 512, "used_pct": 0, "objects": 0, "collections": 0}

# ================= MAINTENANCE =================
async def send_global_maint(update, context):
    msg = f"🔧 <b>{bold('BOT UNDER MAINTENANCE')}</b> 🔧\n\n{small_caps('our team is fixing some issues')}\n{small_caps('please try again later')}\n\n⚡ {small_caps('bot made by')} : {get_bot_credit()}"
    await update.message.reply_text(msg, parse_mode="HTML", reply_parameters=rp(update.message.message_id))

async def send_feature_maint(update, context, feature_name):
    msg = f"🔧 <b>{small_caps(feature_name)} {bold('UNDER MAINTENANCE')}</b> 🔧\n\n{small_caps('this service is under maintenance')}\n{small_caps('we will fix it soon')}\n\n⚡ {small_caps('bot made by')} : {get_bot_credit()}"
    await update.message.reply_text(msg, parse_mode="HTML", reply_parameters=rp(update.message.message_id))

# ================= FORCE JOIN (UPDATED) =================
async def check_all_joined(context, uid):
    chans = load_channels()
    if not get_force_enabled() or not chans: return []
    
    cached = JOIN_CACHE.get(uid)
    if cached:
        val, ts = cached
        if (datetime.now() - ts).total_seconds() < JOIN_TTL: return val
        
    not_joined = []
    for ch in chans:
        if not ch.get("real", True): continue
        try:
            raw_id = ch["username"]
            # Chat ID support (e.g. -100123456789)
            try:
                target_chat = int(raw_id) if raw_id.startswith("-") else raw_id
            except ValueError:
                target_chat = raw_id

            m = await context.bot.get_chat_member(chat_id=target_chat, user_id=uid)
            if m.status not in ["member", "administrator", "creator"]: not_joined.append(ch)
        except: 
            not_joined.append(ch)
            
    JOIN_CACHE[uid] = (not_joined, datetime.now())
    return not_joined

async def send_force_join(update, context):
    chans = load_channels()
    if not chans: return
    buttons = []
    for ch in chans:
        # Colored button added here (style="primary" = Blue)
        buttons.append([InlineKeyboardButton(f"👉 Join {ch['name']}", url=ch["link"], style="primary")])
    buttons.append([InlineKeyboardButton("✅ Verify Joined", callback_data="check_join", style="success")])
    
    kb = InlineKeyboardMarkup(buttons)
    msg = f"🔒 <b>{bold('CHANNEL VERIFICATION REQUIRED')}</b> 🔒\n\n{small_caps('please join the following channels to use this bot')}\n\n"
    for ch in chans: msg += f"• {ch['link']}\n"
    msg += f"\n✅ {small_caps('after joining, click')} '<b>{bold('Verify Joined')}</b>' {small_caps('below')}"
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML",
        reply_parameters=rp(update.message.message_id), disable_web_page_preview=True)

# ================= MENUS =================
def main_menu(uid):
    buttons = [
        [KeyboardButton(f"📱 {small_caps('number info')}", style="primary"),
         KeyboardButton(f"🆔 {small_caps('aadhar info')}", style="primary")],
        [KeyboardButton(f"🎁 {small_caps('refer & earn')}", style="primary"),
         KeyboardButton(f"🎫 {small_caps('redeem code')}", style="success")],
        [KeyboardButton(f"👤 {small_caps('my profile')}", style="success"),
         KeyboardButton(f"🚗 {small_caps('vehicle to num')}", style="primary")],
        [KeyboardButton(f"🆔 {small_caps('tg id info')}", style="danger")]
    ]
    if is_admin(uid):
        buttons.append([KeyboardButton(f"🔧 {small_caps('admin panel')}", style="danger")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def admin_menu():
    toggle = f"🔴 {small_caps('disable force join')}" if get_force_enabled() else f"🟢 {small_caps('enable force join')}"
    maint = f"🔴 {small_caps('toggle maintenance')}" if get_maintenance_global() else f"🟢 {small_caps('toggle maintenance')}"
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"📊 {small_caps('stats')}", style="primary"),
         KeyboardButton(f"📢 {small_caps('broadcast')}", style="primary")],
        [KeyboardButton(f"💰 {small_caps('add credits')}", style="success"),
         KeyboardButton(f"➖ {small_caps('deduct credits')}", style="danger")],
        [KeyboardButton(f"💎 {small_caps('add plan')}", style="success"),
         KeyboardButton(f"❌ {small_caps('remove plan')}", style="danger")],
        [KeyboardButton(f"🎫 {small_caps('generate code')}", style="success"),
         KeyboardButton(f"📋 {small_caps('list codes')}", style="primary")],
        [KeyboardButton(f"🗑 {small_caps('delete code')}", style="danger"),
         KeyboardButton(toggle, style="danger")],
        [KeyboardButton(f"📢 {small_caps('add channel')}", style="primary"),
         KeyboardButton(f"👻 {small_caps('add fake channel')}", style="danger")],
        [KeyboardButton(f"🗑 {small_caps('remove channel')}", style="danger"),
         KeyboardButton(f"📋 {small_caps('list channels')}", style="primary")],
        [KeyboardButton(f"✏️ {small_caps('change bot credit')}", style="primary"),
         KeyboardButton(f"🎁 {small_caps('set welcome bonus')}", style="success")],
        [KeyboardButton(f"📢 {small_caps('credit to all')}", style="success"),
         KeyboardButton(f"🚫 {small_caps('suspend user')}", style="danger")],
        [KeyboardButton(f"✅ {small_caps('unsuspend user')}", style="success"),
         KeyboardButton(f"📋 {small_caps('suspended list')}", style="primary")],
        [KeyboardButton(f"🔧 {small_caps('feature maint')}", style="danger"),
         KeyboardButton(maint, style="danger")],
        [KeyboardButton(f"🔍 {small_caps('check user')}", style="primary"),
         KeyboardButton(f"⬅️ {small_caps('back')}", style="danger")]
    ], resize_keyboard=True)

# ================= API FETCH =================
async def fetch_number(number):
    cache_key = f"number_{number}"
    cached = API_CACHE.get(cache_key)
    if cached:
        data, ts = cached
        if (datetime.now() - ts).total_seconds() < API_CACHE_TTL: return data
    try:
        s = await get_session()
        async with s.get(API_NUMBER.format(term=number)) as r:
            if r.status != 200: return None
            d = await r.json(content_type=None)
            if not d.get("status"): return None
            data_block = d.get("data", {})
            if not data_block or data_block.get("status") != "success": return None
            inner = data_block.get("Data", {})
            main_records = inner.get("Main_Records", [])
            if not main_records: return None
            first = main_records[0]
            record = {
                "id": first.get("id"), "mobile": first.get("mobile"), "name": first.get("name"),
                "fname": first.get("fname"), "address": first.get("address"),
                "alt": first.get("alt"), "circle": first.get("circle"), "email": first.get("email")
            }
            API_CACHE[cache_key] = (record, datetime.now())
            return record
    except: return None

def normalize_aadhar(r):
    return {"id": r.get("aadhaar"), "mobile": r.get("mobile"), "name": r.get("name"),
            "fname": r.get("father_name"), "address": r.get("address"),
            "alt": r.get("alt_mobile"), "circle": r.get("circle"), "email": r.get("email")}

async def fetch_aadhar(a):
    cache_key = f"aadhar_{a}"
    cached = API_CACHE.get(cache_key)
    if cached:
        data, ts = cached
        if (datetime.now() - ts).total_seconds() < API_CACHE_TTL: return data
    try:
        s = await get_session()
        async with s.get(API_AADHAR.format(term=a)) as r:
            if r.status != 200: return None
            d = await r.json(content_type=None)
            if not d.get("success") or not d.get("result"): return None
            recs = [normalize_aadhar(x) for x in d["result"]]
            API_CACHE[cache_key] = (recs, datetime.now())
            return recs
    except: return None

async def fetch_vehicle(v):
    cache_key = f"vehicle_{v}"
    cached = API_CACHE.get(cache_key)
    if cached:
        data, ts = cached
        if (datetime.now() - ts).total_seconds() < API_CACHE_TTL: return data
    try:
        s = await get_session()
        async with s.get(API_VEHICLE.format(term=v)) as r:
            if r.status != 200: return None
            d = await r.json(content_type=None)
            if not d.get("success"): return None
            API_CACHE[cache_key] = (d, datetime.now())
            return d
    except: return None

async def fetch_tg(q):
    cache_key = f"tg_{q}"
    cached = API_CACHE.get(cache_key)
    if cached:
        data, ts = cached
        if (datetime.now() - ts).total_seconds() < API_CACHE_TTL: return data
    try:
        s = await get_session()
        async with s.get(API_TG.format(term=q)) as r:
            if r.status != 200: return None
            d = await r.json(content_type=None)
            if not d.get("status") or not d.get("data", {}).get("success"): return None
            API_CACHE[cache_key] = (d["data"], datetime.now())
            return d["data"]
    except: return None

# ================= MESSAGE BUILDERS =================
def format_record(rec, idx, total):
    msg = f"👤 <b>{small_caps(f'record {idx}/{total}')}</b>\n"
    if rec.get("id"): msg += f"├🪪 <b>{small_caps('aadhaar')}</b>: <code>{rec['id']}</code>\n"
    if rec.get("mobile"): msg += f"├📱 <b>{small_caps('mobile')}</b>: <code>{rec['mobile']}</code>\n"
    if rec.get("name"): msg += f"├👤 <b>{small_caps('name')}</b>: <code>{rec['name'].strip()}</code>\n"
    if rec.get("fname"): msg += f"├👨 <b>{small_caps('father')}</b>: <code>{rec['fname'].strip()}</code>\n"
    if rec.get("address"): msg += f"├🏠 <b>{small_caps('address')}</b>: <code>{rec['address'].strip()}</code>\n"
    if rec.get("alt"): msg += f"├📲 <b>{small_caps('alt mobile')}</b>: <code>{rec['alt']}</code>\n"
    if rec.get("circle"): msg += f"└📡 <b>{small_caps('circle')}</b>: <code>{rec['circle']}</code>\n"
    if rec.get("email"): msg += f"   📧 <b>{small_caps('email')}</b>: <code>{rec['email']}</code>\n"
    return msg

def build_number_msg(number, rec):
    msg = f"📋 <b>{bold('MOBILE NUMBER INFO')}</b>\n━━━━━━━━━━━━━━━━━━\n"
    msg += f"🕐 <b>{datetime.now().strftime('%d %b %Y %I:%M %p')}</b>\n"
    msg += f"📞 <b>{small_caps('number')}</b>: <code>{number}</code>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += format_record(rec, 1, 1)
    msg += "━━━━━━━━━━━━━━━━━━\n"
    msg += f"\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
    return msg

def pagination_kb(page, tp, prefix):
    if tp <= 1: return None
    row = []
    if page > 0: row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_{page - 1}"))
    row.append(InlineKeyboardButton(f"📄 {page + 1}/{tp}", callback_data="noop"))
    if page < tp - 1: row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_{page + 1}"))
    return InlineKeyboardMarkup([row])

def build_aadhar_msg(a, records, page, per_page=3):
    total = len(records)
    start = page * per_page
    pr = records[start:start + per_page]
    tp = (total + per_page - 1) // per_page
    msg = f"🆔 <b>{bold('AADHAR INFO')}</b>\n━━━━━━━━━━━━━━━━━━\n"
    msg += f"🕐 <b>{datetime.now().strftime('%d %b %Y %I:%M %p')}</b>\n"
    msg += f"🪪 <b>{small_caps('aadhaar')}</b>: <code>{a}</code>\n"
    msg += f"📊 <b>{small_caps('total records')}</b>: <code>{total}</code>\n"
    msg += "━━━━━━━━━━━━━━━━━━\n"
    for i, rec in enumerate(pr, start=start + 1):
        msg += format_record(rec, i, total) + "━━━━━━━━━━━━━━━━━━\n"
    msg += f"\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}\n\n"
    msg += f"📄 <b>{small_caps(f'part {page + 1} / {tp}')}</b>"
    return msg

# ================= START =================
async def start(update, context):
    user = update.message.from_user
    uid = user.id
    args = context.args

    existing = users_col.find_one({"user_id": uid})
    if not existing:
        users_col.insert_one({"user_id": uid, "username": user.username, "first_name": user.first_name,
            "credits": get_welcome_bonus(), "referrals": 0, "joined_date": datetime.now().isoformat(),
            "credits_expiry": None, "premium_until": None,
            "blocked": False, "suspended": False, "last_daily": None})
        if args and args[0].startswith("ref_"):
            try:
                ref_id = int(args[0].split("_")[1])
                if ref_id != uid:
                    users_col.update_one({"user_id": ref_id}, {"$inc": {"credits": REFER_REWARD, "referrals": 1}})
                    asyncio.create_task(context.bot.send_message(ref_id,
                        "🔋 <b>You Got a New Referral</b> [@HEXASUPORT]", parse_mode="HTML"))
            except Exception as e:
                logging.error(f"Referral error: {e}")
        asyncio.create_task(context.bot.send_message(OWNER_ID, f"🙂New User Started Bot\n\n👉 User: {uid}"))
    else:
        users_col.update_one({"user_id": uid}, {"$set": {"username": user.username, "first_name": user.first_name}})

    if get_maintenance_global() and not is_admin(uid):
        await send_global_maint(update, context); return
    if is_suspended(uid):
        await update.message.reply_text("⛔ You are suspended from using this bot.\n\nContact: @hexasuport",
            reply_parameters=rp(update.message.message_id)); return
    if get_force_enabled() and load_channels() and not is_admin(uid):
        if await check_all_joined(context, uid):
            await send_force_join(update, context); return

    claimed = claim_daily(uid)
    u = get_user(uid)
    credits_disp = "ᴜɴʟɪᴍɪᴛᴇᴅ 💎" if has_unlimited(uid) else str(u.get('credits', 0))
    premium_disp = "ᴜɴʟɪᴍɪᴛᴇᴅ" if has_unlimited(uid) else "ɴᴏ"

    msg = f"❤️ <b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ ʙᴏᴛ</b>\n"
    msg += f"👋 <b>ʜᴇʟʟᴏ {user.first_name} !</b>\n\n"
    msg += f"ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ ʙᴏᴛ!\n\n"
    msg += f"💰 <b>ᴄʀᴇᴅɪᴛꜱ</b> : <code>{credits_disp}</code>\n"
    msg += f"🎁 <b>ᴅᴀɪʟʏ</b> : <code>+{get_daily_bonus()}</code>\n"
    msg += f"💎 <b>ᴩʀᴇᴍɪᴜᴍ</b> : <code>{premium_disp}</code>\n\n"
    msg += f"━━━━━━━━━━━━━━━━━━\n⚡ ʙᴏᴛ ᴍᴀᴅᴇ ʙʏ : {get_bot_credit()}"
    if claimed: msg += f"\n\n🎉 <b>+{get_daily_bonus()} Daily Bonus Claimed!</b>"

    await update.message.reply_text(msg, parse_mode="HTML",
        reply_markup=main_menu(uid), reply_parameters=rp(update.message.message_id))

# ================= GROUP COMMANDS =================
async def cmd_num(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/num 7979072441</code>", parse_mode="HTML"); return
    number = context.args[0]
    if not number.isdigit() or len(number) != 10:
        await update.message.reply_text("❌ Invalid number."); return
    if not has_unlimited(uid) and get_user(uid).get('credits', 0) < 1:
        await update.message.reply_text(not_enough_msg(), parse_mode="HTML"); return
    if not has_unlimited(uid):
        users_col.update_one({"user_id": uid}, {"$inc": {"credits": -1}})
        if uid in USER_CACHE: USER_CACHE[uid]["credits"] -= 1
    proc = await update.message.reply_text(f"🔍 <b>{bold('Searching...')}</b>", parse_mode="HTML")
    rec = await fetch_number(number)
    if not rec:
        refund_credit(uid); await proc.edit_text(no_data_msg("number"), parse_mode="HTML"); return
    await proc.edit_text(build_number_msg(number, rec), parse_mode="HTML")

async def cmd_aadhar(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/aadhar 216958447184</code>", parse_mode="HTML"); return
    a = context.args[0]
    if not a.isdigit() or len(a) != 12:
        await update.message.reply_text("❌ Invalid Aadhaar."); return
    if not has_unlimited(uid) and get_user(uid).get('credits', 0) < 1:
        await update.message.reply_text(not_enough_msg(), parse_mode="HTML"); return
    if not has_unlimited(uid):
        users_col.update_one({"user_id": uid}, {"$inc": {"credits": -1}})
        if uid in USER_CACHE: USER_CACHE[uid]["credits"] -= 1
    proc = await update.message.reply_text(f"🔍 <b>{bold('Searching...')}</b>", parse_mode="HTML")
    recs = await fetch_aadhar(a)
    if not recs:
        refund_credit(uid); await proc.edit_text(no_data_msg("aadhar"), parse_mode="HTML"); return
    AADHAR_PAGINATION[uid] = {"records": recs, "aadhar": a}
    tp = (len(recs) + 3 - 1) // 3
    await proc.edit_text(build_aadhar_msg(a, recs, 0), parse_mode="HTML", reply_markup=pagination_kb(0, tp, "aadharpage"))

async def cmd_vehicle(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/vehicle UP85BQ0130</code>", parse_mode="HTML"); return
    v = context.args[0].upper()
    if not has_unlimited(uid) and get_user(uid).get('credits', 0) < 1:
        await update.message.reply_text(not_enough_msg(), parse_mode="HTML"); return
    if not has_unlimited(uid):
        users_col.update_one({"user_id": uid}, {"$inc": {"credits": -1}})
        if uid in USER_CACHE: USER_CACHE[uid]["credits"] -= 1
    proc = await update.message.reply_text(f"🔍 <b>{bold('Searching...')}</b>", parse_mode="HTML")
    d = await fetch_vehicle(v)
    if not d:
        refund_credit(uid); await proc.edit_text(no_data_msg("vehicle"), parse_mode="HTML"); return
    msg = f"🚗 <b>{bold('VEHICLE TO NUM')}</b>\n━━━━━━━━━━━━━━━━━━\n"
    fields = [('owner','owner_name'),('mobile','mobile_number'),('vehicle','vehicle'),
              ('manufacturer','manufacturer'),('reg no','registration_number'),
              ('chassis','chassis_number'),('engine','engine_number'),('fuel','fuel_type'),
              ('rc status','rc_status'),('reg date','registration_date'),
              ('insurance','insurance_company'),('insurance upto','insurance_upto'),
              ('address','permanent_address'),('rto','rto')]
    for lb, key in fields:
        val = d.get(key)
        if val: msg += f"├ <b>{small_caps(lb)}</b>: <code>{val}</code>\n"
    msg += f"\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
    await proc.edit_text(msg, parse_mode="HTML")

async def cmd_tg(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: <code>/tg 6416284194</code>", parse_mode="HTML"); return
    q = context.args[0].strip()
    if q.startswith("@"): q = q[1:]
    if not has_unlimited(uid) and get_user(uid).get('credits', 0) < 1:
        await update.message.reply_text(not_enough_msg(), parse_mode="HTML"); return
    if not has_unlimited(uid):
        users_col.update_one({"user_id": uid}, {"$inc": {"credits": -1}})
        if uid in USER_CACHE: USER_CACHE[uid]["credits"] -= 1
    proc = await update.message.reply_text(f"🔍 <b>{bold('Searching...')}</b>", parse_mode="HTML")
    d = await fetch_tg(q)
    if not d:
        refund_credit(uid); await proc.edit_text(no_data_msg("tg"), parse_mode="HTML"); return
    msg = f"🆔 <b>{bold('TG ID INFO')}</b>\n━━━━━━━━━━━━━━━━━━\n"
    msg += f"├🆔 <b>{small_caps('tg id')}</b>: <code>{d.get('tg_id','N/A')}</code>\n"
    msg += f"├📱 <b>{small_caps('number')}</b>: <code>{d.get('number','N/A')}</code>\n"
    msg += f"├🌍 <b>{small_caps('country')}</b>: <code>{d.get('country','N/A')}</code>\n"
    msg += f"└☎️ <b>{small_caps('country code')}</b>: <code>{d.get('country_code','N/A')}</code>\n"
    msg += f"\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
    await proc.edit_text(msg, parse_mode="HTML")

async def cmd_profile(update, context):
    uid = update.effective_user.id
    u = get_user(uid)
    name = update.effective_user.first_name
    uname = f"@{update.effective_user.username}" if update.effective_user.username else "N/A"
    credits = "UNLIMITED 💎" if has_unlimited(uid) else str(u.get('credits',0))
    is_premium = has_unlimited(uid); premium_disp = "YES" if is_premium else "NO"
    expiry_disp = "N/A"
    if is_premium and u.get("premium_until"):
        try: expiry_disp = datetime.fromisoformat(u["premium_until"]).strftime('%d %b %Y')
        except: pass
    msg = f"👤 <b>{small_caps('my profile')}</b>\n━━━━━━━━━━━━━━━━━━\n"
    msg += f"├👤 <b>{small_caps('name')}</b>: <code>{name}</code>\n"
    msg += f"├🔗 <b>{small_caps('username')}</b>: <code>{uname}</code>\n"
    msg += f"├🆔 <b>{small_caps('user id')}</b>: <code>{uid}</code>\n"
    msg += f"├💎 <b>{small_caps('credits')}</b>: <code>{credits}</code>\n"
    msg += f"├👥 <b>{small_caps('referrals')}</b>: <code>{u.get('referrals',0)}</code>\n"
    msg += f"├💠 <b>{small_caps('premium')}</b>: <code>{premium_disp}</code>\n"
    msg += f"└⏳ <b>{small_caps('expiry')}</b>: <code>{expiry_disp}</code>\n\n"
    msg += f"⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
    await update.message.reply_text(msg, parse_mode="HTML")

async def cmd_help(update, context):
    msg = f"📋 <b>{bold('COMMANDS')}</b>\n🔢 <code>/num 7979072441</code>\n🆔 <code>/aadhar 216958447184</code>\n🚗 <code>/vehicle UP85BQ0130</code>\n🆔 <code>/tg 6416284194</code>\n👤 <code>/profile</code>\n\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
    await update.message.reply_text(msg, parse_mode="HTML")

# ================= MAIN TEXT HANDLER =================
async def handle_text(update, context):
    if update.effective_chat.type in ['group', 'supergroup']: return
    uid = update.message.from_user.id

    if get_maintenance_global() and not is_admin(uid):
        await send_global_maint(update, context); return
    if is_suspended(uid):
        await update.message.reply_text("⛔ You are suspended.\n\nContact: @hexasuport",
            reply_parameters=rp(update.message.message_id)); return
    if get_force_enabled() and load_channels() and not is_admin(uid):
        if await check_all_joined(context, uid):
            await send_force_join(update, context); return

    text = update.message.text
    msg_id = update.message.message_id

    # ================= ADMIN =================
    if is_admin(uid):
        if text == f"🔧 {small_caps('admin panel')}":
            await update.message.reply_text(f"<b>🔧 {small_caps('admin panel')}</b>",
                reply_markup=admin_menu(), parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"⬅️ {small_caps('back')}":
            await update.message.reply_text(f"<b>{small_caps('back')}</b>",
                reply_markup=main_menu(uid), parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🟢 {small_caps('enable force join')}":
            set_setting("force_enabled", True)
            await update.message.reply_text(f"✅ <b>{small_caps('force join enabled')}</b>",
                reply_markup=admin_menu(), parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🔴 {small_caps('disable force join')}":
            set_setting("force_enabled", False)
            await update.message.reply_text(f"✅ <b>{small_caps('force join disabled')}</b>",
                reply_markup=admin_menu(), parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text in [f"🟢 {small_caps('toggle maintenance')}", f"🔴 {small_caps('toggle maintenance')}"]:
            ns = not get_maintenance_global(); set_setting("maintenance_global", ns)
            await update.message.reply_text(f"🔧 <b>Global Maintenance: {'ENABLED ✅' if ns else 'DISABLED ❌'}</b>",
                reply_markup=admin_menu(), parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🔧 {small_caps('feature maint')}":
            features = get_maint_features(); buttons = []
            for code, label in FEATURES:
                mark = "✅" if code in features else "❌"
                buttons.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"fm_{code}")])
            await update.message.reply_text(f"<b>🔧 {small_caps('feature maintenance')}</b>",
                reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"📊 {small_caps('stats')}":
            tu = users_col.count_documents({}); blocked = users_col.count_documents({"blocked": True})
            suspended = users_col.count_documents({"suspended": True}); active = tu - blocked - suspended
            cr = list(users_col.aggregate([{"$group": {"_id": None, "s": {"$sum": "$credits"}}}]))
            tc = cr[0]["s"] if cr else 0
            fj = "ON ✅" if get_force_enabled() else "OFF ❌"
            gm = "ON 🔧" if get_maintenance_global() else "OFF ✅"
            mongo = get_mongo_stats()
            msg = f"📊 <b>{bold('BOT STATS')}</b>\n━━━━━━━━━━━━━━━━━━\n"
            msg += f"👥 <b>{small_caps('users')}</b>: <code>{tu}</code>\n"
            msg += f"✅ <b>{small_caps('active')}</b>: <code>{active}</code>\n"
            msg += f"🚫 <b>{small_caps('blocked')}</b>: <code>{blocked}</code>\n"
            msg += f"⛔ <b>{small_caps('suspended')}</b>: <code>{suspended}</code>\n"
            msg += f"💰 <b>{small_caps('total credits')}</b>: <code>{tc}</code>\n"
            msg += f"🎫 <b>{small_caps('redeem codes')}</b>: <code>{redeem_col.count_documents({})}</code>\n"
            msg += f"🎁 <b>{small_caps('welcome bonus')}</b>: <code>{get_welcome_bonus()}</code>\n"
            msg += f"📅 <b>{small_caps('daily bonus')}</b>: <code>+{get_daily_bonus()}</code>\n"
            msg += f"📢 <b>{small_caps('channels')}</b>: <code>{len(load_channels())}</code>\n"
            msg += f"🔒 <b>{small_caps('force join')}</b>: <code>{fj}</code>\n"
            msg += f"🔧 <b>{small_caps('maintenance')}</b>: <code>{gm}</code>\n"
            msg += f"\n━━━━━━━━━━━━━━━━━━\n🗄 <b>{bold('MONGO DB')}</b>\n"
            msg += f"📦 <b>{small_caps('used')}</b>: <code>{mongo['storage_size']} MB / {mongo['free_limit']} MB</code>\n"
            msg += f"📊 <b>{small_caps('usage')}</b>: <code>{mongo['used_pct']}%</code>\n"
            msg += f"💾 <b>{small_caps('free')}</b>: <code>{mongo['free_mb']} MB</code>\n"
            msg += f"📄 <b>{small_caps('objects')}</b>: <code>{mongo['objects']}</code>\n"
            msg += f"📚 <b>{small_caps('collections')}</b>: <code>{mongo['collections']}</code>"
            await update.message.reply_text(msg, parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"📢 {small_caps('broadcast')}":
            context.user_data['admin_state'] = 'broadcast'
            await update.message.reply_text("Send text, photo, video or document to broadcast:", reply_parameters=rp(msg_id)); return
        if text == f"💰 {small_caps('add credits')}":
            context.user_data['admin_state'] = 'add_credits'
            await update.message.reply_text("Format:\n<code>user_id amount days</code>", parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"➖ {small_caps('deduct credits')}":
            context.user_data['admin_state'] = 'deduct_credits'
            await update.message.reply_text("Send: user_id amount", reply_parameters=rp(msg_id)); return
        if text == f"💎 {small_caps('add plan')}":
            context.user_data['admin_state'] = 'add_plan'
            await update.message.reply_text("Send: user_id days", reply_parameters=rp(msg_id)); return
        if text == f"❌ {small_caps('remove plan')}":
            context.user_data['admin_state'] = 'remove_plan'
            await update.message.reply_text("Send user_id:", reply_parameters=rp(msg_id)); return
        if text == f"🎫 {small_caps('generate code')}":
            context.user_data['admin_state'] = 'gen_code'
            await update.message.reply_text("Send: credits max_uses", reply_parameters=rp(msg_id)); return
        if text == f"📋 {small_caps('list codes')}":
            codes = list(redeem_col.find({}))
            if not codes: await update.message.reply_text("No codes.", reply_parameters=rp(msg_id))
            else:
                m = "<b>📋 Codes:</b>\n\n"
                for c in codes: m += f"<code>{c['code']}</code> - <b>{c['credits']} cr</b>, used {c.get('used_count',0)}/{c['max_uses']}\n"
                await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id))
            return
        if text == f"🗑 {small_caps('delete code')}":
            context.user_data['admin_state'] = 'del_code'
            await update.message.reply_text("Send code:", reply_parameters=rp(msg_id)); return
        if text == f"📢 {small_caps('add channel')}":
            context.user_data['admin_state'] = 'add_channel'
            await update.message.reply_text("Format:\n<code>Name | @username | https://t.me/link</code>", parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"👻 {small_caps('add fake channel')}":
            context.user_data['admin_state'] = 'add_fake_channel'
            await update.message.reply_text("Format:\n<code>Name | @username | https://t.me/link</code>", parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🗑 {small_caps('remove channel')}":
            context.user_data['admin_state'] = 'remove_channel'
            chans = load_channels()
            m = "<b>Send channel username to remove (with @):</b>\n\n"
            if not chans: m = "<b>No channels to remove.</b>"
            else:
                for ch in chans:
                    tag = "👻" if not ch.get("real", True) else "📢"
                    m += f"{tag} <code>{ch['username']}</code>\n"
            await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"📋 {small_caps('list channels')}":
            chans = load_channels()
            if not chans: await update.message.reply_text("No channels set.", reply_parameters=rp(msg_id)); return
            m = f"<b>📋 Channels ({len(chans)})</b>\n\n"
            for i, ch in enumerate(chans, 1):
                tag = "👻 FAKE" if not ch.get("real", True) else "📢 REAL"
                m += f"{i}. {tag}\n   <b>{ch['name']}</b> | <code>{ch['username']}</code>\n\n"
            await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id), disable_web_page_preview=True); return
        if text == f"✏️ {small_caps('change bot credit')}":
            context.user_data['admin_state'] = 'change_bot_credit'
            await update.message.reply_text(f"Current: <b>{get_bot_credit()}</b>\n\nSend new value (with @):", parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🎁 {small_caps('set welcome bonus')}":
            context.user_data['admin_state'] = 'set_welcome'
            await update.message.reply_text(f"Current: <b>{get_welcome_bonus()}</b>\n\nSend new value:", parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"📢 {small_caps('credit to all')}":
            context.user_data['admin_state'] = 'credit_all'
            await update.message.reply_text("Format: <code>amount [days]</code>", parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🚫 {small_caps('suspend user')}":
            context.user_data['admin_state'] = 'suspend_user'
            await update.message.reply_text("Send user_id:", reply_parameters=rp(msg_id)); return
        if text == f"✅ {small_caps('unsuspend user')}":
            context.user_data['admin_state'] = 'unsuspend_user'
            await update.message.reply_text("Send user_id:", reply_parameters=rp(msg_id)); return
        if text == f"📋 {small_caps('suspended list')}":
            sus = list(users_col.find({"suspended": True}))
            if not sus: await update.message.reply_text("No suspended users.", reply_parameters=rp(msg_id)); return
            m = f"<b>📋 Suspended ({len(sus)})</b>\n\n"
            for u in sus[:20]: m += f"• <code>{u['user_id']}</code> - {u.get('first_name','N/A')}\n"
            await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
        if text == f"🔍 {small_caps('check user')}":
            context.user_data['admin_state'] = 'check_user'
            await update.message.reply_text("Send user_id:", reply_parameters=rp(msg_id)); return

        st = context.user_data.get('admin_state')
        if st == 'change_bot_credit':
            new_val = text.strip()
            set_setting("bot_credit", new_val)
            await update.message.reply_text(f"✅ Bot credit updated to: <b>{new_val}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'add_credits':
            try:
                p = text.split(); t = int(p[0]); a = int(p[1]); days = int(p[2]) if len(p) > 2 else 0
                add_credits(t, a, days)
                m = f"✅ Added <b>{a}</b> to <b>{t}</b>"
                if days > 0: m += f"\n📅 Expires in <b>{days}</b> days"
                await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Format: user_id amount days", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'deduct_credits':
            try:
                p = text.split(); t = int(p[0]); a = int(p[1])
                users_col.update_one({"user_id": t}, {"$inc": {"credits": -a}}, upsert=True)
                if t in USER_CACHE: USER_CACHE[t]["credits"] -= a
                await update.message.reply_text(f"✅ Deducted <b>{a}</b> from <b>{t}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Format: user_id amount", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'add_plan':
            try:
                p = text.split(); t = int(p[0]); days = int(p[1]) if len(p) > 1 else 30
                exp = (datetime.now() + timedelta(days=days)).isoformat()
                users_col.update_one({"user_id": t}, {"$set": {"premium_until": exp}}, upsert=True)
                if t in USER_CACHE: USER_CACHE[t]["premium_until"] = exp
                await update.message.reply_text(f"✅ Plan activated for <b>{t}</b>\n📅 {days} days", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Format: user_id days", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'remove_plan':
            try:
                t = int(text.strip())
                users_col.update_one({"user_id": t}, {"$set": {"premium_until": None}})
                if t in USER_CACHE: USER_CACHE[t]["premium_until"] = None
                await update.message.reply_text(f"✅ Plan removed from <b>{t}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Invalid", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'gen_code':
            try:
                p = text.split(); code = uuid.uuid4().hex[:8].upper()
                redeem_col.insert_one({"code": code, "credits": int(p[0]),
                    "max_uses": int(p[1]) if len(p) > 1 else 1, "used_count": 0, "used_by": []})
                await update.message.reply_text(f"Code: <code>{code}</code>", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Use: credits max_uses", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'del_code':
            r = redeem_col.delete_one({"code": text.strip().upper()})
            await update.message.reply_text("Deleted." if r.deleted_count else "Not found.", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'add_channel':
            try:
                parts = [p.strip() for p in text.split("|")]
                if len(parts) != 3: raise ValueError
                name, username, link = parts
                if not username.startswith("@") and not username.startswith("-"): username = "@" + username
                chans = load_channels()
                if any(c['username'].lower() == username.lower() for c in chans):
                    await update.message.reply_text("❌ Already exists.", reply_parameters=rp(msg_id))
                else:
                    chans.append({"name": name, "username": username, "link": link, "real": True})
                    save_channels(chans)
                    await update.message.reply_text(f"✅ Added: <b>{name}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Format: Name | @username | link", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'add_fake_channel':
            try:
                parts = [p.strip() for p in text.split("|")]
                if len(parts) != 3: raise ValueError
                name, username, link = parts
                if not username.startswith("@") and not username.startswith("-"): username = "@" + username
                chans = load_channels()
                if any(c['username'].lower() == username.lower() for c in chans):
                    await update.message.reply_text("❌ Already exists.", reply_parameters=rp(msg_id))
                else:
                    chans.append({"name": name, "username": username, "link": link, "real": False})
                    save_channels(chans)
                    await update.message.reply_text(f"✅ Fake added: <b>{name}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Format: Name | @username | link", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'remove_channel':
            username = text.strip()
            if not username.startswith("@") and not username.startswith("-"): username = "@" + username
            chans = load_channels()
            new = [c for c in chans if c['username'].lower() != username.lower()]
            if len(new) == len(chans): await update.message.reply_text("❌ Not found.", reply_parameters=rp(msg_id))
            else:
                save_channels(new)
                await update.message.reply_text(f"✅ Removed: <b>{username}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'set_welcome':
            try:
                val = int(text.strip())
                if val < 0: raise ValueError
                set_setting("welcome_bonus", val)
                await update.message.reply_text(f"✅ Welcome bonus: <b>{val}</b>", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Send a number", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'credit_all':
            try:
                p = text.split(); amt = int(p[0]); days = int(p[1]) if len(p) > 1 else 0
                update = {"$inc": {"credits": amt}}
                if days > 0: update["$set"] = {"credits_expiry": (datetime.now() + timedelta(days=days)).isoformat()}
                n = users_col.count_documents({})
                users_col.update_many({}, update)
                USER_CACHE.clear()
                await update.message.reply_text(f"✅ Added <b>{amt}</b> credits to <b>{n}</b> users", parse_mode="HTML", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Format: amount [days]", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'suspend_user':
            try:
                t = int(text.strip())
                users_col.update_one({"user_id": t}, {"$set": {"suspended": True, "suspended_at": datetime.now().isoformat()}}, upsert=True)
                if t in USER_CACHE: USER_CACHE[t]["suspended"] = True
                await update.message.reply_text(f"⛔ User <b>{t}</b> suspended.", parse_mode="HTML", reply_parameters=rp(msg_id))
                try: await context.bot.send_message(t, "⛔ You are suspended from using this bot.\n\nContact: @hexasuport")
                except: pass
            except: await update.message.reply_text("❌ Invalid", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'unsuspend_user':
            try:
                t = int(text.strip())
                users_col.update_one({"user_id": t}, {"$set": {"suspended": False, "suspended_at": None}})
                if t in USER_CACHE: USER_CACHE[t]["suspended"] = False
                await update.message.reply_text(f"✅ User <b>{t}</b> unsuspended.", parse_mode="HTML", reply_parameters=rp(msg_id))
                try: await context.bot.send_message(t, "✅ You have been unsuspended.")
                except: pass
            except: await update.message.reply_text("❌ Invalid", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'check_user':
            try:
                t = int(text.strip())
                d = users_col.find_one({"user_id": t})
                if d:
                    name = d.get("first_name", "N/A"); uname = d.get("username")
                    uname_disp = f"@{uname}" if uname else "N/A"
                    is_premium = False; premium_exp = "N/A"
                    if d.get("premium_until"):
                        try:
                            p_dt = datetime.fromisoformat(d["premium_until"])
                            if datetime.now() < p_dt: is_premium = True; premium_exp = p_dt.strftime("%d %b %Y")
                            else: premium_exp = "Expired"
                        except: pass
                    credits_disp = "UNLIMITED 💎" if is_premium else str(d.get("credits", 0))
                    cred_exp = "No expiry"
                    if d.get("credits_expiry"):
                        try:
                            c = datetime.fromisoformat(d["credits_expiry"])
                            cred_exp = c.strftime("%d %b %Y") if datetime.now() < c else "Expired"
                        except: pass
                    joined = d.get("joined_date", "N/A")
                    if joined and joined != "N/A": joined = joined[:10]
                    blocked = "YES 🚫" if d.get("blocked") else "NO"
                    suspended = "YES ⛔" if d.get("suspended") else "NO"
                    m = f"👤 <b>{small_caps('user details')}</b>\n━━━━━━━━━━━━━━━━━━\n"
                    m += f"├👤 <b>{small_caps('name')}</b>: <code>{name}</code>\n"
                    m += f"├🔗 <b>{small_caps('username')}</b>: <code>{uname_disp}</code>\n"
                    m += f"├🆔 <b>{small_caps('user id')}</b>: <code>{t}</code>\n"
                    m += f"├💎 <b>{small_caps('credits')}</b>: <code>{credits_disp}</code>\n"
                    m += f"├⏳ <b>{small_caps('credits expiry')}</b>: <code>{cred_exp}</code>\n"
                    m += f"├👥 <b>{small_caps('referrals')}</b>: <code>{d.get('referrals',0)}</code>\n"
                    m += f"├💠 <b>{small_caps('premium')}</b>: <code>{'YES' if is_premium else 'NO'}</code>\n"
                    m += f"├📅 <b>{small_caps('premium till')}</b>: <code>{premium_exp}</code>\n"
                    m += f"├🚫 <b>{small_caps('blocked')}</b>: <code>{blocked}</code>\n"
                    m += f"├⛔ <b>{small_caps('suspended')}</b>: <code>{suspended}</code>\n"
                    m += f"└📆 <b>{small_caps('joined')}</b>: <code>{joined}</code>"
                    await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id))
                else: await update.message.reply_text("❌ Not found.", reply_parameters=rp(msg_id))
            except: await update.message.reply_text("❌ Invalid", reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return
        if st == 'broadcast':
            all_u = list(users_col.find({}, {"user_id": 1}))
            sent = 0; blk = 0
            for u in all_u:
                try:
                    await context.bot.send_message(u["user_id"], text, parse_mode="HTML"); sent += 1
                except Forbidden:
                    if not users_col.find_one({"user_id": u["user_id"]}, {"blocked": 1}).get("blocked"):
                        users_col.update_one({"user_id": u["user_id"]}, {"$set": {"blocked": True}})
                        blk += 1
                        try:
                            nm = users_col.find_one({"user_id": u["user_id"]}, {"first_name": 1}).get("first_name", "N/A")
                            await context.bot.send_message(OWNER_ID, f"🚫 User Blocked Bot\n\n👉 User ID: <code>{u['user_id']}</code>\n👉 Name: {nm}", parse_mode="HTML")
                        except: pass
                except: pass
            out = f"✅ Sent to {sent}/{len(all_u)}"
            if blk: out += f"\n🚫 {blk} blocked"
            await update.message.reply_text(out, reply_parameters=rp(msg_id))
            context.user_data.pop('admin_state', None); return

    # ================= USER FEATURES =================
    if text == f"📱 {small_caps('number info')}":
        if is_feature_maint("number"): await send_feature_maint(update, context, "number info"); return
        context.user_data['state'] = 'number'
        m = "📱 ꜱᴇɴᴅ 10-ᴅɪɢɪᴛ ᴍᴏʙɪʟᴇ ɴᴜᴍʙᴇʀ\nᴇxᴀᴍᴩʟᴇ: 9876543210\n\n"
        m += f"⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
    if text == f"🆔 {small_caps('aadhar info')}":
        if is_feature_maint("aadhar"): await send_feature_maint(update, context, "aadhar info"); return
        context.user_data['state'] = 'aadhar'
        m = f"🆔 {small_caps('send 12-digit aadhar number')}\n{small_caps('example')}: 649964855626\n\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
    if text == f"🚗 {small_caps('vehicle to num')}":
        if is_feature_maint("vehicle"): await send_feature_maint(update, context, "vehicle to num"); return
        context.user_data['state'] = 'vehicle'
        m = "🚗 ꜱᴇɴᴅ ᴠᴇʜɪᴄʟᴇ ʀᴇɢɪꜱᴛʀᴀᴛɪᴏɴ ɴᴜᴍʙᴇʀ\nᴇxᴀᴍᴩʟᴇ: UP85BQ0130\n\n⚡ " + small_caps('bot made by') + f" : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
    if text == f"🆔 {small_caps('tg id info')}":
        if is_feature_maint("tg"): await send_feature_maint(update, context, "tg id info"); return
        context.user_data['state'] = 'tg'
        m = "🆔 ꜱᴇɴᴅ ᴛᴇʟᴇɢʀᴀᴍ ᴜꜱᴇʀɴᴀᴍᴇ ᴡɪᴛʜᴏᴜᴛ @ ᴏʀ ᴜꜱᴇʀ ɪᴅ\nᴇxᴀᴍᴩʟᴇ: 6416284194\n\n⚡ " + small_caps('bot made by') + f" : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
    if text == f"🎁 {small_caps('refer & earn')}":
        if is_feature_maint("refer"): await send_feature_maint(update, context, "refer & earn"); return
        bu = (await context.bot.get_me()).username
        link = f"https://t.me/{bu}?start=ref_{uid}"
        u = get_user(uid); refs = u.get('referrals', 0)
        credits = "UNLIMITED 💎" if has_unlimited(uid) else str(u.get('credits', 0))
        m = f"👥 <b>{small_caps('referrals')}</b>\n📊 <b>{small_caps('total')}</b> : <code>{refs}</code>\n\n"
        m += f"🔗 <b>{small_caps('your link')}</b> :\n<code>{link}</code>\n\n"
        m += f"🎁 <b>{small_caps('per referral')}</b> : <code>+{REFER_REWARD}</code> {small_caps('credits')}\n"
        m += f"💰 <b>{small_caps('your credits')}</b> : <code>{credits}</code>\n\n"
        m += f"━━━━━━━━━━━━━━━━━━\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
    if text == f"🎫 {small_caps('redeem code')}":
        if is_feature_maint("redeem"): await send_feature_maint(update, context, "redeem code"); return
        context.user_data['state'] = 'redeem'
        m = f"🎫 {small_caps('send your redeem code')}\n{small_caps('example')}: ABC123XYZ\n\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return
    if text == f"👤 {small_caps('my profile')}":
        if is_feature_maint("profile"): await send_feature_maint(update, context, "my profile"); return
        u = get_user(uid)
        name = update.message.from_user.first_name
        uname = f"@{update.message.from_user.username}" if update.message.from_user.username else "N/A"
        credits = "UNLIMITED 💎" if has_unlimited(uid) else str(u.get('credits',0))
        is_premium = has_unlimited(uid); premium_disp = "YES" if is_premium else "NO"
        expiry_disp = "N/A"
        if is_premium and u.get("premium_until"):
            try: expiry_disp = datetime.fromisoformat(u["premium_until"]).strftime('%d %b %Y')
            except: pass
        m = f"👤 <b>{small_caps('my profile')}</b>\n━━━━━━━━━━━━━━━━━━\n"
        m += f"├👤 <b>{small_caps('name')}</b>: <code>{name}</code>\n"
        m += f"├🔗 <b>{small_caps('username')}</b>: <code>{uname}</code>\n"
        m += f"├🆔 <b>{small_caps('user id')}</b>: <code>{uid}</code>\n"
        m += f"├💎 <b>{small_caps('credits')}</b>: <code>{credits}</code>\n"
        m += f"├👥 <b>{small_caps('referrals')}</b>: <code>{u.get('referrals',0)}</code>\n"
        m += f"├💠 <b>{small_caps('premium')}</b>: <code>{premium_disp}</code>\n"
        m += f"└⏳ <b>{small_caps('expiry')}</b>: <code>{expiry_disp}</code>\n\n"
        m += f"⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
        await update.message.reply_text(m, parse_mode="HTML", reply_parameters=rp(msg_id)); return

    st = context.user_data.get('state')
    if st == 'redeem':
        code = text.strip().upper()
        d = redeem_col.find_one({"code": code})
        if not d: await update.message.reply_text("❌ Invalid code.", reply_parameters=rp(msg_id))
        elif d.get('used_count', 0) >= d.get('max_uses', 1): await update.message.reply_text("❌ Usage limit reached.", reply_parameters=rp(msg_id))
        elif uid in d.get('used_by', []): await update.message.reply_text("❌ Already used.", reply_parameters=rp(msg_id))
        else:
            add_credits(uid, d['credits'], 0)
            redeem_col.update_one({"code": code}, {"$inc": {"used_count": 1}, "$push": {"used_by": uid}})
            await update.message.reply_text(f"✅ Redeemed! <b>+{d['credits']}</b> credits.", parse_mode="HTML", reply_parameters=rp(msg_id))
        context.user_data.pop('state', None); return

    if st in ('number', 'aadhar', 'vehicle', 'tg'):
        u = get_user(uid)
        unlimited = has_unlimited(uid)
        if not unlimited and u.get('credits', 0) < 1:
            await update.message.reply_text(not_enough_msg(), parse_mode="HTML", reply_parameters=rp(msg_id))
            context.user_data.pop('state', None); return
        if not unlimited:
            users_col.update_one({"user_id": uid}, {"$inc": {"credits": -1}})
            if uid in USER_CACHE: USER_CACHE[uid]["credits"] -= 1
            u['credits'] -= 1

        proc = await update.message.reply_text(f"🔍 <b>{bold('Searching...')}</b>\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}",
            parse_mode="HTML", reply_parameters=rp(msg_id))

        if st == 'number':
            if not text.isdigit() or len(text) != 10:
                await proc.edit_text("❌ Invalid number. Must be 10 digits."); refund_credit(uid)
            else:
                rec = await fetch_number(text)
                if not rec:
                    await proc.edit_text(no_data_msg("number"), parse_mode="HTML"); refund_credit(uid)
                else:
                    await proc.edit_text(build_number_msg(text, rec), parse_mode="HTML")
                    bal = "UNLIMITED 💎" if unlimited else str(u.get('credits', 0))
                    await context.bot.send_message(uid, f"<b>💵 {small_caps('credits left')}</b>: <code>{bal}</code>", parse_mode="HTML", reply_parameters=rp(msg_id))
        elif st == 'aadhar':
            if not text.isdigit() or len(text) != 12:
                await proc.edit_text("❌ Invalid Aadhaar. Must be 12 digits."); refund_credit(uid)
            else:
                recs = await fetch_aadhar(text)
                if not recs:
                    await proc.edit_text(no_data_msg("aadhar"), parse_mode="HTML"); refund_credit(uid)
                else:
                    AADHAR_PAGINATION[uid] = {"records": recs, "aadhar": text}
                    tp = (len(recs) + 3 - 1) // 3
                    await proc.edit_text(build_aadhar_msg(text, recs, 0), parse_mode="HTML", reply_markup=pagination_kb(0, tp, "aadharpage"))
                    bal = "UNLIMITED 💎" if unlimited else str(u.get('credits', 0))
                    await context.bot.send_message(uid, f"<b>💵 {small_caps('credits left')}</b>: <code>{bal}</code>", parse_mode="HTML", reply_parameters=rp(msg_id))
        elif st == 'vehicle':
            d = await fetch_vehicle(text.upper())
            if not d:
                await proc.edit_text(no_data_msg("vehicle"), parse_mode="HTML"); refund_credit(uid)
            else:
                m = f"🚗 <b>{bold('VEHICLE TO NUM')}</b>\n━━━━━━━━━━━━━━━━━━\n"
                fields = [('owner','owner_name'),('mobile','mobile_number'),('vehicle','vehicle'),
                          ('manufacturer','manufacturer'),('reg no','registration_number'),
                          ('chassis','chassis_number'),('engine','engine_number'),('fuel','fuel_type'),
                          ('rc status','rc_status'),('reg date','registration_date'),
                          ('insurance','insurance_company'),('insurance upto','insurance_upto'),
                          ('address','permanent_address'),('rto','rto')]
                for lb, key in fields:
                    val = d.get(key)
                    if val: m += f"├ <b>{small_caps(lb)}</b>: <code>{val}</code>\n"
                m += f"\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
                await proc.edit_text(m, parse_mode="HTML")
                bal = "UNLIMITED 💎" if unlimited else str(u.get('credits', 0))
                await context.bot.send_message(uid, f"<b>💵 {small_caps('credits left')}</b>: <code>{bal}</code>", parse_mode="HTML", reply_parameters=rp(msg_id))
        elif st == 'tg':
            q = text.strip()
            if q.startswith("@"): q = q[1:]
            if not q:
                await proc.edit_text("❌ Invalid TG ID or username."); refund_credit(uid)
            else:
                d = await fetch_tg(q)
                if not d:
                    await proc.edit_text(no_data_msg("tg"), parse_mode="HTML"); refund_credit(uid)
                else:
                    m = f"🆔 <b>{bold('TG ID INFO')}</b>\n━━━━━━━━━━━━━━━━━━\n"
                    m += f"├🆔 <b>{small_caps('tg id')}</b>: <code>{d.get('tg_id','N/A')}</code>\n"
                    m += f"├📱 <b>{small_caps('number')}</b>: <code>{d.get('number','N/A')}</code>\n"
                    m += f"├🌍 <b>{small_caps('country')}</b>: <code>{d.get('country','N/A')}</code>\n"
                    m += f"└☎️ <b>{small_caps('country code')}</b>: <code>{d.get('country_code','N/A')}</code>\n"
                    m += f"\n⚡ <b>{small_caps('bot made by')}</b> : {get_bot_credit()}"
                    await proc.edit_text(m, parse_mode="HTML")
                    bal = "UNLIMITED 💎" if unlimited else str(u.get('credits', 0))
                    await context.bot.send_message(uid, f"<b>💵 {small_caps('credits left')}</b>: <code>{bal}</code>", parse_mode="HTML", reply_parameters=rp(msg_id))
        context.user_data.pop('state', None); return

    await update.message.reply_text(f"<b>{small_caps('please select an option')}</b>",
        reply_markup=main_menu(uid), parse_mode="HTML", reply_parameters=rp(msg_id))

# ================= MEDIA HANDLER =================
async def media_handler(update, context):
    uid = update.message.from_user.id
    if not is_admin(uid): return
    if context.user_data.get('admin_state') != 'broadcast': return
    all_u = list(users_col.find({}, {"user_id": 1}))
    sent = 0; blk = 0
    msg = update.message; caption = msg.caption or ""
    for u in all_u:
        try:
            if msg.photo: await context.bot.send_photo(u["user_id"], msg.photo[-1].file_id, caption=caption, parse_mode="HTML")
            elif msg.video: await context.bot.send_video(u["user_id"], msg.video.file_id, caption=caption, parse_mode="HTML")
            elif msg.document: await context.bot.send_document(u["user_id"], msg.document.file_id, caption=caption, parse_mode="HTML")
            elif msg.audio: await context.bot.send_audio(u["user_id"], msg.audio.file_id, caption=caption, parse_mode="HTML")
            sent += 1
        except Forbidden:
            if not users_col.find_one({"user_id": u["user_id"]}, {"blocked": 1}).get("blocked"):
                users_col.update_one({"user_id": u["user_id"]}, {"$set": {"blocked": True}}); blk += 1
                try:
                    nm = users_col.find_one({"user_id": u["user_id"]}, {"first_name": 1}).get("first_name", "N/A")
                    await context.bot.send_message(OWNER_ID, f"🚫 User Blocked Bot\n\n👉 User ID: <code>{u['user_id']}</code>\n👉 Name: {nm}", parse_mode="HTML")
                except: pass
        except: pass
    out = f"✅ Sent to {sent}/{len(all_u)}"
    if blk: out += f"\n🚫 {blk} blocked"
    await update.message.reply_text(out, reply_parameters=rp(update.message.message_id))
    context.user_data.pop('admin_state', None)

# ================= CALLBACKS =================
async def check_join_cb(update, context):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    JOIN_CACHE.pop(uid, None)
    if not await check_all_joined(context, uid):
        try: await q.message.delete()
        except: pass
        await context.bot.send_message(uid, f"<b>✅ {small_caps('verified!')}\n\n{small_caps('select an option')}</b>",
            reply_markup=main_menu(uid), parse_mode="HTML")
    else:
        await q.answer("❌ Please join all channels first!", show_alert=True)

async def num_page_cb(update, context):
    q = update.callback_query; await q.answer()
    if q.data == "noop": return

async def aadhar_page_cb(update, context):
    q = update.callback_query; await q.answer()
    if q.data == "noop": return
    if q.data.startswith("aadharpage_"):
        page = int(q.data.split("_")[1]); uid = q.from_user.id
        d = AADHAR_PAGINATION.get(uid)
        if not d: await q.answer("❌ Session expired.", show_alert=True); return
        recs = d["records"]; a = d["aadhar"]
        tp = (len(recs) + 3 - 1) // 3
        try: await q.edit_message_text(build_aadhar_msg(a, recs, page), parse_mode="HTML", reply_markup=pagination_kb(page, tp, "aadharpage"))
        except: pass

async def feature_maint_cb(update, context):
    q = update.callback_query; await q.answer()
    if not q.data.startswith("fm_"): return
    if not is_admin(q.from_user.id): await q.answer("Not allowed", show_alert=True); return
    code = q.data[3:]
    features = get_maint_features()
    if code in features: features.remove(code)
    else: features.append(code)
    set_setting("maintenance_features", features)
    buttons = []
    for c, label in FEATURES:
        mark = "✅" if c in features else "❌"
        buttons.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"fm_{c}")])
    try: await q.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except: pass

# ================= POST INIT =================
async def post_init(application):
    global ADMIN_CACHE
    users_col.update_many({"credits": {"$exists": False}}, {"$set": {"credits": get_welcome_bonus()}})
    users_col.update_many({"credits_expiry": {"$exists": False}}, {"$set": {"credits_expiry": None}})
    users_col.update_many({"premium_until": {"$exists": False}}, {"$set": {"premium_until": None}})
    users_col.update_many({"blocked": {"$exists": False}}, {"$set": {"blocked": False}})
    users_col.update_many({"suspended": {"$exists": False}}, {"$set": {"suspended": False}})
    users_col.update_many({"last_daily": {"$exists": False}}, {"$set": {"last_daily": None}})
    
    ADMIN_CACHE = {OWNER_ID}
    for d in users_col.find({"is_admin": True}, {"user_id": 1}):
        ADMIN_CACHE.add(d["user_id"])
        
    await application.bot.set_my_commands(
        [BotCommand("start", "🚀 Start"), BotCommand("profile", "👤 Profile")],
        scope=BotCommandScopeAllPrivateChats())
    await application.bot.set_my_commands(
        [BotCommand("num", "🔢 Number Info"), BotCommand("aadhar", "🆔 Aadhar Info"),
         BotCommand("vehicle", "🚗 Vehicle Info"), BotCommand("tg", "🆔 TG ID Info"),
         BotCommand("profile", "👤 Profile"), BotCommand("help", "📋 Help")],
        scope=BotCommandScopeAllGroupChats())
    logging.info(f"Post-init done. Admins: {len(ADMIN_CACHE)}")

# ================= MAIN =================
def main():
    request = HTTPXRequest(connection_pool_size=32, connect_timeout=5.0,
        read_timeout=5.0, write_timeout=5.0, pool_timeout=5.0)
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).post_init(post_init).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("num", cmd_num))
    app.add_handler(CommandHandler("aadhar", cmd_aadhar))
    app.add_handler(CommandHandler("vehicle", cmd_vehicle))
    app.add_handler(CommandHandler("tg", cmd_tg))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(check_join_cb, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(feature_maint_cb, pattern="^fm_"))
    app.add_handler(CallbackQueryHandler(num_page_cb, pattern="^numpage_"))
    app.add_handler(CallbackQueryHandler(aadhar_page_cb, pattern="^aadharpage_"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO, media_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running...")
    app.run_polling(drop_pending_updates=True, poll_interval=0.5, timeout=20)

if __name__ == "__main__":
    main()