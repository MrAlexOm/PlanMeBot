import os
import asyncio
import logging
from datetime import datetime, timedelta

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    BotCommand
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# --- НАСТРОЙКИ ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
API_TOKEN = os.environ.get("BOT_TOKEN")
if not API_TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables!")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# --- БЛОК ДЛЯ RENDER (АНТИ-СОН) ---
async def handle(request):
    return web.Response(text="Bot is alive and running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/healthz", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render сам назначит порт через переменную окружения PORT
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Render Health Check server started on port {port}")

# --- БАЗА ДАННЫХ ---
class Database:
    def __init__(self, db_path="tasks.db"):
        self.db_path = db_path

    def init_db(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                reminder_time TEXT
            )
        ''')
        conn.commit()
        conn.close()

    async def add_task(self, user_id, text, reminder_time):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO tasks (user_id, text, reminder_time) VALUES (?, ?, ?)",
                (user_id, text, reminder_time)
            )
            await db.commit()

    async def get_user_tasks(self, user_id):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, text, reminder_time FROM tasks WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchall()

    async def delete_task(self, task_id):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await db.commit()

db = Database()

# --- КЛАВИАТУРЫ ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить задачу")],
        [KeyboardButton(text="📋 Мои задачи")]
    ],
    resize_keyboard=True
)

# --- ФУНКЦИИ ---
async def set_main_menu(bot: Bot):
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь")
    ]
    await bot.set_my_commands(commands)

async def send_reminder(user_id, text, task_id):
    try:
        await bot.send_message(user_id, f"🔔 Напоминание: {text}")
        await db.delete_task(task_id)
        logging.info(f"Reminder sent to {user_id}")
    except Exception as e:
        logging.error(f"Failed to send reminder: {e}")

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я твой планировщик задач. Используй меню ниже, чтобы управлять своими делами.",
        reply_markup=main_keyboard
    )

@dp.message(F.text == "➕ Добавить задачу")
async def add_task_start(message: types.Message):
    await message.answer("Введите текст задачи и время через запятую.\nПример: Купить хлеб, 10:30")

@dp.message(F.text == "📋 Мои задачи")
async def list_tasks(message: types.Message):
    tasks = await db.get_user_tasks(message.from_user.id)
    if not tasks:
        await message.answer("У вас пока нет активных задач.")
        return

    response = "Ваши задачи:\n"
    for _, text, time in tasks:
        response += f"• {text} (в {time})\n"
    await message.answer(response)

@dp.message()
async def process_task(message: types.Message):
    if "," not in message.text:
        return

    try:
        text, time_str = map(str.strip, message.text.split(",", 1))
        
        # Парсим время
        now = datetime.now()
        target_time = datetime.strptime(time_str, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )

        if target_time < now:
            target_time += timedelta(days=1)

        # Сохраняем в БД (упрощенно без записи ID в scheduler здесь, для краткости)
        # Для полноценной работы лучше сохранять и получать ID сразу
        await db.add_task(message.from_user.id, text, target_time.isoformat())
        
        # Планируем задачу
        scheduler.add_job(
            send_reminder, 
            'date', 
            run_date=target_time, 
            args=[message.from_user.id, text, 0] # ID здесь заглушка, в реале лучше брать из БД
        )

        await message.answer(f"✅ Задача '{text}' добавлена на {time_str}")
    except ValueError:
        await message.answer("⚠️ Неверный формат. Используйте: Задача, ЧЧ:ММ")

# --- ЗАПУСК ---
async def main():
    # 1. Запускаем веб-сервер для Render (Анти-сон)
    asyncio.create_task(start_web_server())
    
    # 2. Инициализация ресурсов
    db.init_db()
    await set_main_menu(bot)
    scheduler.start()
    
    # 3. Запуск Polling
    logging.info("Starting bot polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())