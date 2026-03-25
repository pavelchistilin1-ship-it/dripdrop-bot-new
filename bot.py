import logging
import sqlite3
import os
import subprocess
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
DB_NAME = "dripdrop.db"
ADMIN_USERNAME = "Emagjii"
SUPPORT_BOT_URL = "https://t.me/DripDropSupport_bot"
WELCOME_PHOTO_URL = "https://i.postimg.cc/Dwyx5HHG/IMG-4225.jpg"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = "pavelchistilin1-ship-it/dripdrop-bot-new"

# Состояния для ConversationHandler
ADD_REQ_NUMBER = 1
ADD_REQ_BANK = 2
ADD_REQ_FIO = 3
ADD_REQ_INTERVAL = 4
REPLENISH_AMOUNT = 5

TRAFFIC_INTERVAL = 6
EDIT_REQ_INTERVAL = 7
MOD_SEARCH_USER = 8
MOD_REPLENISH_TYPE = 9
MOD_REPLENISH_AMOUNT = 10
MOD_PAYMENT_DATA = 11
APPROVE_PAYMENT_NUMBER = 12
PROMOTE_MODERATOR = 13
MOD_REPLY_USER = 14

# Функция синхронизации БД с GitHub
def sync_db_to_github():
    try:
        subprocess.run(["git", "config", "--global", "user.email", "bot@dripdrop.pay"], check=False)
        subprocess.run(["git", "config", "--global", "user.name", "DripDropBot"], check=False)
        remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        subprocess.run(["git", "add", DB_NAME], check=True)
        subprocess.run(["git", "commit", "-m", f"Auto-sync DB: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"], check=True)
        subprocess.run(["git", "push", remote_url, "main"], check=True)
        logger.info("База данных успешно синхронизирована с GitHub")
    except Exception as e:
        logger.error(f"Ошибка синхронизации с GitHub: {e}")

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT DEFAULT 'trader',
            insurance_balance REAL DEFAULT 0,
            working_balance REAL DEFAULT 0,
            turnover REAL DEFAULT 0,
            earned REAL DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS requisites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            data TEXT,
            status TEXT DEFAULT 'idle',
            check_interval TEXT DEFAULT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trader_id INTEGER,
            moderator_id INTEGER,
            requisite_id INTEGER,
            data TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("PRAGMA table_info(users)")
    cols = [c[1] for c in cursor.fetchall()]
    if 'earned' not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN earned REAL DEFAULT 0")
    cursor.execute("PRAGMA table_info(requisites)")
    cols = [c[1] for c in cursor.fetchall()]
    if 'status' not in cols:
        cursor.execute("ALTER TABLE requisites ADD COLUMN status TEXT DEFAULT 'idle'")
    if 'check_interval' not in cols:
        cursor.execute("ALTER TABLE requisites ADD COLUMN check_interval TEXT DEFAULT NULL")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_user_by_identifier(identifier):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if identifier.isdigit():
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (int(identifier),))
    else:
        username = identifier.replace("@", "")
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(user_id, username):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def get_moderators():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE role IN ('moderator', 'super_moderator')")
    mods = [row[0] for row in cursor.fetchall()]
    conn.close()
    return mods

def calculate_commission(amount):
    if amount < 100: return 0
    if amount < 1000: return 0.12
    if amount < 5000: return 0.10
    if amount < 10000: return 0.08
    return 0.055

def get_main_keyboard(role):
    if role in ['moderator', 'super_moderator']:
        keyboard = [[KeyboardButton("📤 Платежи"), KeyboardButton("👥 Пользователи")]]
        if role == 'super_moderator':
            keyboard.append([KeyboardButton("🛡️ Назначить модератора")])
        keyboard.append([KeyboardButton("🔄 Режим Трейдера")])
    else:
        keyboard = [
            [KeyboardButton("💎 Баланс"), KeyboardButton("🏦 Реквизиты")],
            [KeyboardButton("🧊 Пополнить"), KeyboardButton("🚦 Трафик")],
            [KeyboardButton("📋 Платежи"), KeyboardButton("🆘 Поддержка")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def sync_job(context: ContextTypes.DEFAULT_TYPE):
    sync_db_to_github()
    logger.info("Плановая синхронизация БД выполнена")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    create_user(user_id, username)
    user = get_user(user_id)
    if username == ADMIN_USERNAME and user[2] != 'super_moderator':
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'super_moderator' WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        user = get_user(user_id)
    role_name = {'trader': 'Трейдер', 'moderator': 'Модератор', 'super_moderator': 'Супер-модератор'}.get(user[2], 'Трейдер')
    welcome_text = (
        f"🌊 **DripDropPay** 🌊\n"
        f"━━━━━━━━━━━━\n"
        f"👤 **Вы вошли как {role_name}**\n"
        f"**#{user_id}**\n"
        f"━━━━━━━━━━━━\n\n"
        f"**[Наш тгк](https://t.me/DripDropInfo)**"
    )
    try:
        await update.message.reply_photo(photo=WELCOME_PHOTO_URL, caption=welcome_text, reply_markup=get_main_keyboard(user[2]), parse_mode='Markdown')
    except:
        await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard(user[2]), parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        return
    if text == "🔄 Режим Трейдера" and user[2] in ['moderator', 'super_moderator']:
        keyboard = [
            [KeyboardButton("💎 Баланс"), KeyboardButton("🏦 Реквизиты")],
            [KeyboardButton("🧊 Пополнить"), KeyboardButton("🚦 Трафик")],
            [KeyboardButton("📋 Платежи"), KeyboardButton("🆘 Поддержка")],
            [KeyboardButton("🔄 Режим Модератора")]
        ]
        await update.message.reply_text("🔄 Режим Трейдера.", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))
    elif text == "🔄 Режим Модератора" and user[2] in ['moderator', 'super_moderator']:
        await update.message.reply_text("🔄 Режим Модератора.", reply_markup=get_main_keyboard(user[2]))
    elif text == "💎 Баланс":
        await update.message.reply_text(
            f"🧊 **Ваши счета**\n━━━━━━━━━━━━\n"
            f"🔹 Страховой: `{user[3]:.2f} ₽`\n"
            f"🔸 Рабочий: `{user[4]:.2f} ₽`\n"
            f"📈 Оборот: `{user[5]:.2f} ₽`\n"
            f"💸 Заработано: `{user[6]:.2f} ₽`\n━━━━━━━━━━━━",
            parse_mode='Markdown'
        )
    elif text == "🏦 Реквизиты":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, data, status, check_interval FROM requisites WHERE user_id = ?", (user_id,))
        reqs = cursor.fetchall()
        conn.close()
        msg = "📋 **Ваши реквизиты**\n━━━━━━━━━━━━\n"
        keyboard = []
        if not reqs:
            msg += "❕ Нет реквизитов."
        else:
            for r in reqs:
                status = "🟢 В работе" if r[2] == 'active' else "⚪️ Свободен"
                interval_text = f" | Интервал: `{r[3]}`" if r[3] else ""
                msg += f"💧 `{r[1]}` {interval_text} | {status}\n"
                keyboard.append([InlineKeyboardButton("✏️ Изменить интервал", callback_data=f"edit_interval_{r[0]}")])
        keyboard.append([InlineKeyboardButton("➕ Добавить", callback_data="add_req"), InlineKeyboardButton("🗑️ Удалить", callback_data="del_req")])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif text == "🧊 Пополнить":
        await update.message.reply_text(
            "💎 Выберите способ пополнения:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🤖 CryptoBot", callback_data="repl_crypto"),
                InlineKeyboardButton("🌐 TRC20", callback_data="repl_trc20")
            ]])
        )
    elif text == "🚦 Трафик":
        if user[3] < 5000:
            await update.message.reply_text("❌ **Ошибка:** Страховой баланс должен быть не менее 5000 ₽.", parse_mode='Markdown')
            return
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, data FROM requisites WHERE user_id = ? AND status = 'idle'", (user_id,))
        reqs = cursor.fetchall()
        conn.close()
        if not reqs:
            await update.message.reply_text("❌ У вас нет свободных реквизитов.")
            return
        keyboard = [[InlineKeyboardButton(f"💧 {r[1]}", callback_data=f"traf_req_{r[0]}")] for r in reqs]
        await update.message.reply_text("🚦 Выберите реквизит для трафика:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif text == "📋 Платежи":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT id, data, amount FROM payments WHERE trader_id = ? AND status = 'pending'", (user_id,))
        pays = cursor.fetchall()
        conn.close()
        if not pays:
            await update.message.reply_text("❕ Нет активных платежей.")
        else:
            for p in pays:
                await update.message.reply_text(
                    f"📦 **Платёж #{p[0]}**\n━━━━━━━━━━━━\n💰 Сумма: `{p[2]:.2f} ₽`\n🏦 Данные: `{p[1]}`",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Одобрить", callback_data=f"appr_pay_{p[0]}")]]),
                    parse_mode='Markdown'
                )
    elif text == "🆘 Поддержка":
        await update.message.reply_text(
            "🆘 **Служба поддержки**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔴 СВЯЗАТЬСЯ С ПОДДЕРЖКОЙ", url=SUPPORT_BOT_URL)]]),
            parse_mode='Markdown'
        )
    elif text == "📤 Платежи" and user[2] in ['moderator', 'super_moderator']:
        await update.message.reply_text("🔍 Введите Username или ID пользователя для создания платежа:")
        context.user_data['mod_action'] = 'payments'
        return MOD_SEARCH_USER
    elif text == "👥 Пользователи" and user[2] in ['moderator', 'super_moderator']:
        await update.message.reply_text("🔍 Введите Username или ID пользователя для просмотра профиля:")
        context.user_data['mod_action'] = 'profile'
        return MOD_SEARCH_USER
    elif text == "🛡️ Назначить модератора" and user[2] == 'super_moderator':
        await update.message.reply_text("🛡️ Введите Username или ID будущего модератора:")
        return PROMOTE_MODERATOR

async def traf_req_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    req_id = query.data.replace("traf_req_", "")
    context.user_data["traf_req_id"] = req_id

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT check_interval FROM requisites WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    interval = row[0] if row else None
    conn.close()

    if not interval:
        await query.edit_message_text("❌ Для этого реквизита не установлен интервал чеков. Пожалуйста, установите его в разделе 'Реквизиты'.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    username = update.effective_user.username

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM requisites WHERE id = ?", (req_id,))
    req_data = cursor.fetchone()[0]
    conn.close()

    mods = get_moderators()
    for mod_id in mods:
        try:
            msg = (
                f"🚦 **Запрос трафика**\n━━━━━━━━━━━━\n"
                f"👤 Трейдер: @{username} (#{user_id})\n"
                f"🏦 Реквизит: `{req_data}`\n"
                f"⏱ Интервал: `{interval}`"
            )
            await context.bot.send_message(
                mod_id, msg,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Принять", callback_data=f"traf_acc_{req_id}_{user_id}"),
                    InlineKeyboardButton("❌ Отклонить", callback_data=f"traf_rej_{req_id}_{user_id}")
                ]]),
                parse_mode='Markdown'
            )
        except:
            pass
    await query.edit_message_text("✅ Запрос трафика отправлен модераторам.")
    return ConversationHandler.END

async def traf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action, req_id, trader_id = data[1], data[2], data[3]
    if action == "acc":
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE requisites SET status = 'active' WHERE id = ?", (req_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(f"✅ Трафик принят для трейдера #{trader_id}")
        await context.bot.send_message(int(trader_id), "🚦 **Трафик принят!** Ваш реквизит теперь активен для работы.", parse_mode='Markdown')
    else:
        await query.edit_message_text(f"❌ Трафик отклонен для трейдера #{trader_id}")
        await context.bot.send_message(int(trader_id), "❌ Ваш запрос на трафик был отклонен модератором.")

async def mod_search_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    identifier = update.message.text
    target = get_user_by_identifier(identifier)
    if not target:
        await update.message.reply_text("❌ Не найден.")
        return ConversationHandler.END
    context.user_data['target_id'] = target[0]
    msg = (
        f"👤 **Профиль**\n━━━━━━━━━━━━\n"
        f"🆔 ID: `{target[0]}`\n"
        f"👤 @{target[1]}\n"
        f"🔹 Страховой: `{target[3]:.2f} ₽`\n"
        f"🔸 Рабочий: `{target[4]:.2f} ₽`\n"
        f"📈 Оборот: `{target[5]:.2f} ₽`\n"
        f"💸 Заработано: `{target[6]:.2f} ₽`"
    )
    
    keyboard = [
        [InlineKeyboardButton("➕ Пополнить", callback_data="mod_repl"), InlineKeyboardButton("➖ Снять", callback_data="mod_withdraw")]
    ]
    
    # Если модератор пришел из раздела "Платежи", добавим кнопку для создания платежа по реквизитам
    if context.user_data.get('mod_action') == 'payments':
        keyboard.append([InlineKeyboardButton("📦 Создать платёж по реквизитам", callback_data="mod_pay_start")])

    await update.message.reply_text(
        msg,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    return MOD_REPLENISH_TYPE

async def mod_pay_req_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    target_id = context.user_data.get('target_id')
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, data, status FROM requisites WHERE user_id = ?", (target_id,))
    reqs = cursor.fetchall()
    conn.close()
    
    if not reqs:
        await query.edit_message_text("❌ У трейдера нет добавленных реквизитов.")
        return ConversationHandler.END
        
    keyboard = []
    for r in reqs:
        prefix = "🟢" if r[2] == 'active' else "⚪️"
        keyboard.append([InlineKeyboardButton(f"{prefix} {r[1]}", callback_data=f"mod_pay_req_{r[0]}")])
        
    await query.edit_message_text("📦 Выберите реквизит для создания платежа:", reply_markup=InlineKeyboardMarkup(keyboard))
    return MOD_PAYMENT_DATA

async def mod_pay_req_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['mod_pay_req_id'] = query.data.replace("mod_pay_req_", "")
    await query.edit_message_text("💰 Введите сумму платежа:")
    return MOD_PAYMENT_DATA

async def mod_payment_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
    except:
        return ConversationHandler.END
    target_id = context.user_data['target_id']
    req_id = context.user_data.get('mod_pay_req_id')
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT data FROM requisites WHERE id = ?", (req_id,))
    row = cursor.fetchone()
    req_data = row[0] if row else "N/A"
    cursor.execute(
        "INSERT INTO payments (trader_id, moderator_id, requisite_id, data, amount) VALUES (?, ?, ?, ?, ?)",
        (target_id, update.effective_user.id, req_id, req_data, amount)
    )
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Платёж отправлен.")
    await context.bot.send_message(target_id, f"📦 Новый платёж: {amount} ₽ на реквизит {req_data}")
    return ConversationHandler.END

async def add_req_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("💧 Введите номер телефона или карты:")
    return ADD_REQ_NUMBER

async def add_req_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_req_number"] = update.message.text
    await update.message.reply_text("🏦 Введите название банка:")
    return ADD_REQ_BANK

async def add_req_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_req_bank"] = update.message.text
    await update.message.reply_text("👤 Введите ФИО полностью:")
    return ADD_REQ_FIO

async def add_req_fio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_req_fio"] = update.message.text
    await update.message.reply_text("⏱ Введите интервал чеков (например: 500-999):")
    return ADD_REQ_INTERVAL

async def add_req_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    number = context.user_data.get("new_req_number")
    bank = context.user_data.get("new_req_bank")
    fio = context.user_data.get("new_req_fio")
    interval = update.message.text
    full_data = f"{number}-{bank}-{fio}"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO requisites (user_id, data, check_interval) VALUES (?, ?, ?)", (user_id, full_data, interval))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Реквизит добавлен.")
    return ConversationHandler.END

async def repl_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['repl_method'] = "CryptoBot" if "crypto" in update.callback_query.data else "TRC20"
    await update.callback_query.edit_message_text(f"🧊 Введите сумму в **$** ({context.user_data['repl_method']}):", parse_mode='Markdown')
    return REPLENISH_AMOUNT

async def repl_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = update.message.text
    user_id, username = update.effective_user.id, update.effective_user.username
    for mod_id in get_moderators():
        try:
            await context.bot.send_message(
                mod_id,
                f"💰 **Пополнение**\n👤 @{username} (#{user_id})\n💵 `{amount} $`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Ответить", callback_data=f"reply_user_{user_id}")]]),
                parse_mode='Markdown'
            )
        except:
            pass
    await update.message.reply_text("✅ Отправлено.")
    return ConversationHandler.END

async def approve_pay_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['approve_pay_id'] = update.callback_query.data.split("_")[2]
    await update.callback_query.edit_message_text("📱 Введите номер отправителя:")
    return APPROVE_PAYMENT_NUMBER

async def approve_pay_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pay_id = context.user_data['approve_pay_id']
    user_id = update.effective_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT amount, moderator_id FROM payments WHERE id = ?", (pay_id,))
    pay = cursor.fetchone()
    if pay:
        amount, mod_id = pay[0], pay[1]
        comm = calculate_commission(amount)
        profit = amount * comm
        cursor.execute(
            "UPDATE users SET working_balance = working_balance - ?, turnover = turnover + ?, earned = earned + ? WHERE user_id = ?",
            (amount, amount, profit, user_id)
        )
        cursor.execute(
            "UPDATE users SET working_balance = working_balance + ? WHERE user_id = ?",
            (profit, user_id)
        )
        cursor.execute("UPDATE payments SET status = 'approved' WHERE id = ?", (pay_id,))
        conn.commit()
        await update.message.reply_text(f"✅ Одобрено! Прибыль: {profit:.2f} ₽")
        try:
            await context.bot.send_message(mod_id, f"✅ Трейдер #{user_id} одобрил платёж #{pay_id} ({amount} ₽). Отправитель: {update.message.text}")
        except:
            pass
    conn.close()
    return ConversationHandler.END

async def mod_reply_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['reply_target_id'] = update.callback_query.data.split("_")[2]
    await update.callback_query.message.reply_text("💬 Введите сообщение:")
    return MOD_REPLY_USER

async def mod_reply_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(
            int(context.user_data['reply_target_id']),
            f"✉️ **От модератора:**\n\n> {update.message.text}",
            parse_mode='Markdown'
        )
    except:
        pass
    await update.message.reply_text("✅ Отправлено.")
    return ConversationHandler.END

async def mod_repl_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['mod_repl_action'] = 'add' if 'repl' in update.callback_query.data else 'sub'
    await update.callback_query.edit_message_text(
        "💎 Тип баланса:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Страховой", callback_data="bal_ins"),
            InlineKeyboardButton("Рабочий", callback_data="bal_work")
        ]])
    )
    return MOD_REPLENISH_AMOUNT

async def mod_repl_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    context.user_data['mod_bal_type'] = 'insurance' if 'ins' in update.callback_query.data else 'working'
    await update.callback_query.edit_message_text("💰 Сумма:")
    return MOD_REPLENISH_AMOUNT

async def mod_repl_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(update.message.text)
    except:
        return ConversationHandler.END
    field = "insurance_balance" if context.user_data.get('mod_bal_type') == "insurance" else "working_balance"
    op = "+" if context.user_data.get('mod_repl_action') == "add" else "-"
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = {field} {op} ? WHERE user_id = ?", (amount, context.user_data['target_id']))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Обновлено.")
    return ConversationHandler.END

async def promote_mod_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = get_user_by_identifier(update.message.text)
    if target:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'moderator' WHERE user_id = ?", (target[0],))
        conn.commit()
        conn.close()
        await update.message.reply_text("✅ Назначен.")
    else:
        await update.message.reply_text("❌ Пользователь не найден.")
    return ConversationHandler.END

async def del_req_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, data FROM requisites WHERE user_id = ?", (update.effective_user.id,))
    reqs = cursor.fetchall()
    conn.close()
    if not reqs:
        await update.callback_query.edit_message_text("Нет реквизитов.")
    else:
        keyboard = [[InlineKeyboardButton(f"🗑️ {r[1]}", callback_data=f"del_id_{r[0]}")] for r in reqs]
        await update.callback_query.edit_message_text("Удалить:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def del_req_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM requisites WHERE id = ?", (update.callback_query.data.split("_")[2],))
    conn.commit()
    conn.close()
    await update.callback_query.edit_message_text("✅ Удалено.")

async def edit_req_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    req_id = update.callback_query.data.split("_")[2]
    context.user_data["edit_req_id"] = req_id
    await update.callback_query.edit_message_text("⏱ Введите новый интервал чеков (например: 500-999):")
    return EDIT_REQ_INTERVAL

async def edit_req_interval_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req_id = context.user_data.get("edit_req_id")
    new_interval = update.message.text
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE requisites SET check_interval = ? WHERE id = ?", (new_interval, req_id))
    conn.commit()
    conn.close()
    await update.message.reply_text("✅ Интервал чеков обновлен.")
    return ConversationHandler.END

def main():
    init_db()
    application = Application.builder().token("8619908903:AAE5Ds0ts3rhViOw0AIzwGLEOGSzfEja0_k").build()
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_req_start, pattern="^add_req$"),
            CallbackQueryHandler(repl_start, pattern="^repl_"),
            CallbackQueryHandler(mod_reply_start, pattern="^reply_user_"),
            CallbackQueryHandler(traf_req_select, pattern="^traf_req_"),
            CallbackQueryHandler(edit_req_interval_start, pattern="^edit_interval_"),
            CallbackQueryHandler(approve_pay_start, pattern="^appr_pay_"),
            MessageHandler(filters.Regex("^(📤 Платежи|👥 Пользователи|🛡️ Назначить модератора)$"), handle_message)
        ],
        states={
            ADD_REQ_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_req_number)],
            ADD_REQ_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_req_bank)],
            ADD_REQ_FIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_req_fio)],
            ADD_REQ_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_req_interval)],
            REPLENISH_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, repl_finish)],
            MOD_REPLY_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, mod_reply_finish)],
            MOD_SEARCH_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, mod_search_user)],
            MOD_REPLENISH_TYPE: [CallbackQueryHandler(mod_repl_type, pattern="^mod_")],
            MOD_REPLENISH_AMOUNT: [
                CallbackQueryHandler(mod_repl_amount, pattern="^bal_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mod_repl_finish)
            ],
            MOD_REPLENISH_TYPE: [
                CallbackQueryHandler(mod_repl_type, pattern="^mod_(repl|withdraw)$"),
                CallbackQueryHandler(mod_pay_req_list, pattern="^mod_pay_start$")
            ],
            MOD_PAYMENT_DATA: [
                CallbackQueryHandler(mod_pay_req_select, pattern="^mod_pay_req_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mod_payment_save)
            ],
            APPROVE_PAYMENT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, approve_pay_finish)],
            PROMOTE_MODERATOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, promote_mod_finish)],
            EDIT_REQ_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_req_interval_finish)]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv)
    application.add_handler(CallbackQueryHandler(del_req_start, pattern="^del_req$"))
    application.add_handler(CallbackQueryHandler(del_req_confirm, pattern="^del_id_"))
    application.add_handler(CallbackQueryHandler(traf_callback, pattern="^traf_(acc|rej)_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    job_queue = application.job_queue
    job_queue.run_repeating(sync_job, interval=600, first=600)
    application.run_polling()

if __name__ == '__main__':
    main()
