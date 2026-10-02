import asyncio
import os
import secrets
from datetime import datetime, timezone

import aiosqlite
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
BOT_NAME = os.getenv("BOT_NAME", "Earn with AK")
MIN_WITHDRAW = float(os.getenv("MIN_WITHDRAW", "110"))
DB = "earn_with_ak.db"

dp = Dispatcher()

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

async def db():
    return await aiosqlite.connect(DB)

async def init_db():
    async with await db() as c:
        await c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            referred_by INTEGER,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            reward REAL NOT NULL,
            type TEXT NOT NULL,
            target TEXT,
            active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS completions(
            user_id INTEGER,
            task_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            PRIMARY KEY(user_id, task_id)
        );
        CREATE TABLE IF NOT EXISTS ledger(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            kind TEXT,
            note TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS withdrawals(
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            method TEXT,
            account TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            admin_note TEXT
        );
        """)
        await c.commit()

async def get_user(uid):
    async with await db() as c:
        cur = await c.execute("SELECT * FROM users WHERE id=?", (uid,))
        return await cur.fetchone()

async def ensure_user(message: Message, referrer=None):
    uid = message.from_user.id
    existing = await get_user(uid)
    if existing:
        return existing
    referred_by = None
    if referrer and referrer != uid and await get_user(referrer):
        referred_by = referrer
    async with await db() as c:
        await c.execute(
            "INSERT INTO users(id,username,first_name,referred_by,created_at) VALUES(?,?,?,?,?)",
            (uid, message.from_user.username, message.from_user.first_name, referred_by, now())
        )
        if referred_by:
            # Referral bonus is configurable in code; 10 BDT in this MVP.
            bonus = 10.0
            await c.execute("UPDATE users SET balance=balance+?, referral_count=referral_count+1 WHERE id=?",
                            (bonus, referred_by))
            await c.execute("INSERT INTO ledger(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
                            (referred_by, bonus, "referral", f"Referral bonus for user {uid}", now()))
        await c.commit()
    return await get_user(uid)

def main_kb():
    kb = InlineKeyboardBuilder()
    buttons = [
        ("🟨 📋 কাজ করুন", "tasks"),
        ("🟨 💰 আমার ব্যালেন্স", "balance"),
        ("🟨 👥 রেফারেল", "referral"),
        ("🟨 💸 টাকা উত্তোলন", "withdraw"),
        ("🟨 📊 ইনকাম হিস্ট্রি", "history"),
        ("🟨 🎁 বোনাস", "bonus"),
        ("🟨 🆘 সাপোর্ট", "support"),
    ]
    for text, cb in buttons:
        kb.button(text=text, callback_data=cb)
    kb.adjust(2)
    return kb.as_markup()

async def home_text(uid):
    u = await get_user(uid)
    return (
        f"🖤 <b>{BOT_NAME}</b> 🖤\n\n"
        f"👋 স্বাগতম, <b>{u[2] or 'বন্ধু'}</b>!\n\n"
        f"💰 ব্যালেন্স: <b>{u[3]:.2f} BDT</b>\n"
        f"👥 রেফারেল: <b>{u[4]}</b>\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"✨ <b>কাজ করুন • আয় করুন • উত্তোলন করুন</b>\n"
        f"━━━━━━━━━━━━━━"
    )

@dp.message(CommandStart())
async def start(message: Message):
    ref = None
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_"):
        try: ref = int(parts[1][4:])
        except ValueError: pass
    await ensure_user(message, ref)
    await message.answer(await home_text(message.from_user.id), reply_markup=main_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.edit_text(await home_text(call.from_user.id), reply_markup=main_kb(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "balance")
async def balance(call: CallbackQuery):
    u = await get_user(call.from_user.id)
    await call.message.edit_text(
        f"🖤 <b>আমার ব্যালেন্স</b>\n\n"
        f"💰 বর্তমান ব্যালেন্স: <b>{u[3]:.2f} BDT</b>\n"
        f"👥 মোট রেফারেল: <b>{u[4]}</b>\n\n"
        f"💸 Minimum withdrawal: <b>{MIN_WITHDRAW:.0f} BDT</b>",
        reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ মেনু", callback_data="home")
    return kb.as_markup()

@dp.callback_query(F.data == "tasks")
async def tasks(call: CallbackQuery):
    async with await db() as c:
        cur = await c.execute("SELECT id,title,reward,type,target FROM tasks WHERE active=1 ORDER BY id DESC")
        rows = await cur.fetchall()
    kb = InlineKeyboardBuilder()
    text = "🖤 <b>📋 কাজ করুন</b>\n\n"
    if not rows:
        text += "এই মুহূর্তে কোনো active task নেই।"
    else:
        for tid, title, reward, typ, target in rows:
            text += f"🟨 <b>{title}</b> — {reward:.2f} BDT\n"
            kb.button(text=f"▶️ {title[:24]} (+{reward:g})", callback_data=f"task:{tid}")
        kb.adjust(1)
    kb.button(text="⬅️ মেনু", callback_data="home")
    await call.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("task:"))
async def task_detail(call: CallbackQuery):
    tid = int(call.data.split(":")[1])
    async with await db() as c:
        cur = await c.execute("SELECT id,title,reward,type,target FROM tasks WHERE id=? AND active=1", (tid,))
        row = await cur.fetchone()
        cur = await c.execute("SELECT status FROM completions WHERE user_id=? AND task_id=?", (call.from_user.id, tid))
        done = await cur.fetchone()
    if not row:
        await call.answer("Task আর available নেই।", show_alert=True); return
    tid, title, reward, typ, target = row
    text = f"🖤 <b>{title}</b>\n\n💰 Reward: <b>{reward:.2f} BDT</b>\n🔎 Type: <b>{typ}</b>\n"
    if done:
        text += f"\n📌 Status: <b>{done[0]}</b>"
        kb = back_kb()
    else:
        text += "\n⚠️ কাজ সম্পন্ন করার পর verification হবে।"
        kb = InlineKeyboardBuilder()
        if target and target.startswith(("http://","https://","tg://")):
            kb.button(text="🔗 কাজের লিংক", url=target)
        elif target and target.startswith("@"):
            kb.button(text="📢 Telegram খুলুন", url=f"https://t.me/{target[1:]}")
        kb.button(text="✅ সম্পন্ন করেছি", callback_data=f"claim:{tid}")
        kb.button(text="⬅️ কাজের তালিকা", callback_data="tasks")
        kb.adjust(1)
    await call.message.edit_text(text, reply_markup=kb.as_markup() if hasattr(kb, "as_markup") else kb, parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("claim:"))
async def claim(call: CallbackQuery):
    tid = int(call.data.split(":")[1])
    async with await db() as c:
        cur = await c.execute("SELECT title,reward,type,target FROM tasks WHERE id=? AND active=1", (tid,))
        row = await cur.fetchone()
        if not row:
            await call.answer("Task পাওয়া যায়নি।", show_alert=True); return
        title, reward, typ, target = row
        cur = await c.execute("SELECT 1 FROM completions WHERE user_id=? AND task_id=?", (call.from_user.id, tid))
        if await cur.fetchone():
            await call.answer("এই task ইতিমধ্যে claim করা হয়েছে।", show_alert=True); return

        status = "pending"
        # Telegram join verification can be added only when bot is admin in the channel.
        # To avoid false credits, all claims are pending by default in this MVP.
        await c.execute("INSERT INTO completions(user_id,task_id,status,created_at) VALUES(?,?,?,?)",
                        (call.from_user.id, tid, status, now()))
        await c.commit()
    await call.message.edit_text(
        f"🟨 <b>{title}</b>\n\n"
        f"⏳ আপনার completion <b>pending verification</b> আছে।\n"
        f"Verification সফল হলে <b>{reward:.2f} BDT</b> balance-এ যোগ হবে।",
        reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "referral")
async def referral(call: CallbackQuery):
    me = await call.bot.get_me()
    u = await get_user(call.from_user.id)
    link = f"https://t.me/{me.username}?start=ref_{call.from_user.id}"
    await call.message.edit_text(
        f"🖤 <b>👥 My Referrals</b>\n\n"
        f"👥 আপনার রেফারেল: <b>{u[4]}</b>\n"
        f"🎁 Referral bonus: <b>10 BDT</b>\n\n"
        f"🔗 আপনার লিংক:\n<code>{link}</code>",
        reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "history")
async def history(call: CallbackQuery):
    async with await db() as c:
        cur = await c.execute("SELECT amount,kind,note,created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 10",
                              (call.from_user.id,))
        rows = await cur.fetchall()
    text = "🖤 <b>📊 ইনকাম হিস্ট্রি</b>\n\n"
    if not rows: text += "এখনও কোনো earning record নেই।"
    else:
        for amount, kind, note, created in rows:
            text += f"🟨 +{amount:.2f} BDT — {kind}\n"
            text += f"   {note}\n"
    await call.message.edit_text(text, reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "withdraw")
async def withdraw_menu(call: CallbackQuery):
    u = await get_user(call.from_user.id)
    kb = InlineKeyboardBuilder()
    for m in ("bKash", "Nagad", "Rocket"):
        kb.button(text=f"💳 {m}", callback_data=f"wdmethod:{m}")
    kb.button(text="⬅️ মেনু", callback_data="home")
    kb.adjust(1)
    await call.message.edit_text(
        f"🖤 <b>💸 টাকা উত্তোলন</b>\n\n"
        f"💰 আপনার ব্যালেন্স: <b>{u[3]:.2f} BDT</b>\n"
        f"🔻 Minimum: <b>{MIN_WITHDRAW:.0f} BDT</b>\n\n"
        f"Payment method নির্বাচন করুন:",
        reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("wdmethod:"))
async def wd_method(call: CallbackQuery):
    method = call.data.split(":",1)[1]
    await call.message.edit_text(
        f"🖤 <b>{method} Withdrawal</b>\n\n"
        f"উদাহরণ:\n<code>/withdraw {method} 110 01XXXXXXXXX</code>\n\n"
        f"অথবা সরাসরি এই format-এ পাঠান:\n"
        f"<code>/withdraw {method} AMOUNT NUMBER</code>\n\n"
        f"⚠️ Payment number সঠিকভাবে দিন।",
        reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

@dp.message(Command("withdraw"))
async def withdraw_cmd(message: Message):
    await ensure_user(message)
    parts = message.text.split()
    if len(parts) != 4:
        await message.answer("Format: /withdraw bKash 110 01XXXXXXXXX")
        return
    method, amount_s, account = parts[1], parts[2], parts[3]
    if method not in {"bKash","Nagad","Rocket"}:
        await message.answer("Payment method: bKash, Nagad অথবা Rocket")
        return
    try: amount = float(amount_s)
    except ValueError:
        await message.answer("Amount সঠিক দিন।"); return
    u = await get_user(message.from_user.id)
    if amount < MIN_WITHDRAW:
        await message.answer(f"Minimum withdrawal {MIN_WITHDRAW:.0f} BDT")
        return
    if amount > u[3]:
        await message.answer("আপনার balance যথেষ্ট নয়।")
        return
    wid = "WD" + secrets.token_hex(5).upper()
    async with await db() as c:
        await c.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, message.from_user.id))
        await c.execute("INSERT INTO withdrawals(id,user_id,method,account,amount,status,created_at) VALUES(?,?,?,?,?,?,?)",
                        (wid, message.from_user.id, method, account, amount, "pending", now()))
        await c.execute("INSERT INTO ledger(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
                        (message.from_user.id, -amount, "withdraw_hold", wid, now()))
        await c.commit()
    await message.answer(f"🟨 Withdrawal request created!\nID: <code>{wid}</code>\nStatus: Pending", parse_mode="HTML")
    for admin in ADMIN_IDS:
        try:
            await message.bot.send_message(admin, f"💸 <b>New withdrawal</b>\nID: <code>{wid}</code>\nUser: <code>{message.from_user.id}</code>\nMethod: {method}\nAccount: <code>{account}</code>\nAmount: {amount:.2f} BDT", parse_mode="HTML")
        except Exception:
            pass

@dp.callback_query(F.data == "bonus")
async def bonus(call: CallbackQuery):
    await call.message.edit_text(
        "🖤 <b>🎁 বোনাস</b>\n\n"
        "বোনাস campaign admin panel থেকে চালু করা যাবে।\n"
        "ভুয়া/অযাচাইকৃত bonus balance যোগ করা হবে না।",
        reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "support")
async def support(call: CallbackQuery):
    await call.message.edit_text(
        "🖤 <b>🆘 Support</b>\n\n"
        "সমস্যা হলে আপনার User ID এবং Withdrawal/Task ID সহ admin/support-এ যোগাযোগ করুন।",
        reply_markup=back_kb(), parse_mode="HTML")
    await call.answer()

@dp.message(Command("addtask"))
async def addtask(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = [x.strip() for x in message.text.split("|")]
    if len(parts) != 5:
        await message.answer("Format:\n/addtask | title | reward | type | target")
        return
    _, title, reward_s, typ, target = parts
    try: reward = float(reward_s)
    except ValueError:
        await message.answer("Reward number হতে হবে."); return
    async with await db() as c:
        await c.execute("INSERT INTO tasks(title,reward,type,target) VALUES(?,?,?,?)",
                        (title,reward,typ,target))
        await c.commit()
    await message.answer("✅ Task added.")

@dp.message(Command("approve"))
async def approve(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split()
    if len(parts) != 2: return
    wid = parts[1]
    async with await db() as c:
        cur = await c.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?", (wid,))
        row = await cur.fetchone()
        if not row:
            await message.answer("Withdrawal পাওয়া যায়নি."); return
        uid, amount, status = row
        if status != "pending":
            await message.answer("Already processed."); return
        await c.execute("UPDATE withdrawals SET status='paid' WHERE id=?", (wid,))
        await c.commit()
    await message.answer(f"✅ {wid} marked as PAID.\nActual payout should be completed through your authorized payment channel/API.")
    try: await message.bot.send_message(uid, f"✅ আপনার withdrawal <code>{wid}</code> paid হিসেবে mark করা হয়েছে।", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("reject"))
async def reject(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2: return
    wid = parts[1]
    reason = parts[2] if len(parts) > 2 else "No reason"
    async with await db() as c:
        cur = await c.execute("SELECT user_id,amount,status FROM withdrawals WHERE id=?", (wid,))
        row = await cur.fetchone()
        if not row:
            await message.answer("Withdrawal পাওয়া যায়নি."); return
        uid, amount, status = row
        if status != "pending":
            await message.answer("Already processed."); return
        await c.execute("UPDATE withdrawals SET status='rejected',admin_note=? WHERE id=?", (reason,wid))
        await c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount,uid))
        await c.execute("INSERT INTO ledger(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
                        (uid, amount, "withdraw_refund", f"{wid}: {reason}", now()))
        await c.commit()
    await message.answer(f"↩️ {wid} rejected and balance refunded.")
    try: await message.bot.send_message(uid, f"↩️ Withdrawal <code>{wid}</code> rejected.\nReason: {reason}\nBalance refunded.", parse_mode="HTML")
    except Exception: pass

@dp.message(Command("credit"))
async def credit(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3: return
    try: uid, amount = int(parts[1]), float(parts[2].split()[0])
    except Exception: return
    note = parts[2]
    async with await db() as c:
        await c.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount,uid))
        await c.execute("INSERT INTO ledger(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)",
                        (uid,amount,"admin_credit",note,now()))
        await c.commit()
    await message.answer("✅ Balance credited and logged.")

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Create .env from .env.example")
    await init_db()
    bot = Bot(BOT_TOKEN)
    print(f"{BOT_NAME} is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
