import asyncio
import logging
import os  # Добавили для порта
from datetime import datetime, timedelta
import pytz

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, BotCommand
from aiohttp import web  # Добавили для веб-сервера

import config
import database as db
import weather_service
from apscheduler.schedulers.asyncio import AsyncIOScheduler
# --- БЛОК ДЛЯ RENDER (АНТИ-СОН) ---
async def handle(request):
    return web.Response(text="Bot is alive!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/healthz", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")
# --- БЛОК ДЛЯ RENDER (АНТИ-СОН) ---
async def handle(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    # Render сам подставит нужный порт в переменную PORT
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")
# ----------------------------------

# Настройка логов
logging.basicConfig(level=logging.INFO)

# Тбилиси UTC+4
TZ = pytz.timezone('Asia/Tbilisi')

# Берем токен из переменных окружения (для безопасности)
TOKEN = os.environ.get("BOT_TOKEN") 
# Если на тесте локально токена в системе нет, берем из config
if not TOKEN:
    TOKEN = config.TOKEN

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone=TZ)

# Состояния бота
class Form(StatesGroup):
    waiting_for_task = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_city = State()

# Отправка уведомления
async def send_reminder(chat_id, task, lang, weather_info):
    try:
        w_text = f"\n\n{weather_info}" if weather_info else ""
        text = config.LOCALES[lang]['notify'].format(task=task, weather=w_text)
        await bot.send_message(chat_id, text)
        logging.info(f"Reminder sent to {chat_id}")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")

# Настройка кнопки "Меню"
async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="/start", description="🚀 Main Menu"),
        BotCommand(command="/help", description="❓ Help"),
    ]
    await bot.set_my_commands(main_menu_commands)

# Команда /START
@dp.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    await state.clear()
    db.init_db()
    lang = db.get_user_lang(message.from_user.id)
    kb = [
        [KeyboardButton(text=config.LOCALES[lang]['menu_add'])],
        [KeyboardButton(text=config.LOCALES[lang]['menu_list']), 
         KeyboardButton(text=config.LOCALES[lang]['menu_lang'])]
    ]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    await message.answer(config.LOCALES[lang]['start'], reply_markup=keyboard)

# Выбор языка
@dp.message(F.text.in_([config.LOCALES[l]['menu_lang'] for l in config.LOCALES]))
async def change_lang_menu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = [[types.InlineKeyboardButton(text="English 🇺🇸", callback_data="setlang_en")],
          [types.InlineKeyboardButton(text="Русский 🇷🇺", callback_data="setlang_ru")],
          [types.InlineKeyboardButton(text="Italiano 🇮🇹", callback_data="setlang_it")]]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer("Select language / Выберите язык / Scegli la lingua:", reply_markup=keyboard)

# Добавить задачу
@dp.message(F.text.in_([config.LOCALES[l]['menu_add'] for l in config.LOCALES]))
async def ask_task(message: types.Message, state: FSMContext):
    await state.clear()
    lang = db.get_user_lang(message.from_user.id)
    await message.answer(config.LOCALES[lang]['ask_task'], reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_task)

@dp.message(Form.waiting_for_task)
async def get_task(message: types.Message, state: FSMContext):
    if message.text.startswith('/'): return
    await state.update_data(task=message.text)
    lang = db.get_user_lang(message.from_user.id)
    
    kb = [[KeyboardButton(text=config.LOCALES[lang]['today']), 
           KeyboardButton(text=config.LOCALES[lang]['tomorrow'])]]
    keyboard = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    await message.answer(config.LOCALES[lang]['ask_date'], reply_markup=keyboard)
    await state.set_state(Form.waiting_for_date)

@dp.message(Form.waiting_for_date)
async def get_date(message: types.Message, state: FSMContext):
    if message.text.startswith('/'): return
    lang = db.get_user_lang(message.from_user.id)
    today = datetime.now(TZ).date()
    txt = message.text.strip()
    
    is_today = any(txt.lower() == config.LOCALES[l]['today'].lower() for l in config.LOCALES)
    is_tomorrow = any(txt.lower() == config.LOCALES[l]['tomorrow'].lower() for l in config.LOCALES)

    if is_today:
        date_res = today
    elif is_tomorrow:
        date_res = today + timedelta(days=1)
    else:
        try:
            date_res = datetime.strptime(txt, "%Y-%m-%d").date()
        except:
            await message.answer("⚠️ Format: YYYY-MM-DD (2026-02-01)")
            return

    await state.update_data(date=str(date_res))
    await message.answer(config.LOCALES[lang]['ask_time'], reply_markup=ReplyKeyboardRemove())
    await state.set_state(Form.waiting_for_time)

@dp.message(Form.waiting_for_time)
async def get_time(message: types.Message, state: FSMContext):
    if message.text.startswith('/'): return
    t_txt = message.text.strip().replace("24:00", "00:00") 
    
    if ":" not in t_txt:
        await message.answer("⚠️ Format: HH:MM (e.g. 15:30)")
        return
        
    await state.update_data(time=t_txt)
    lang = db.get_user_lang(message.from_user.id)
    await message.answer(config.LOCALES[lang]['ask_city'])
    await state.set_state(Form.waiting_for_city)

@dp.message(Form.waiting_for_city)
async def get_city(message: types.Message, state: FSMContext):
    if message.text.startswith('/'): return
    city = message.text.strip()
    data = await state.get_data()
    lang = db.get_user_lang(message.from_user.id)
    
    try:
        full_time_str = f"{data['date']} {data['time']}"
        target_datetime = datetime.strptime(full_time_str, "%Y-%m-%d %H:%M")
        target_datetime = TZ.localize(target_datetime)
        
        if target_datetime < datetime.now(TZ):
            await message.answer("❌ Past time! Choose future.")
            await state.clear()
            return

        weather_info = ""
        if city.lower() != '/skip':
            try:
                weather_info = weather_service.get_weather(city, data['date'])
            except:
                weather_info = "Weather service busy"

        scheduler.add_job(
            send_reminder, 'date', run_date=target_datetime, 
            args=[message.chat.id, data['task'], lang, weather_info],
            id=f"{message.chat.id}_{target_datetime.timestamp()}"
        )
        
        await message.answer(config.LOCALES[lang]['success'].format(time=full_time_str))
        await state.clear()
    except Exception as e:
        logging.error(f"Final error: {e}")
        await message.answer("⚠️ Error! Try /start")
        await state.clear()

@dp.callback_query(F.data.startswith("setlang_"))
async def set_language(callback: types.CallbackQuery):
    new_lang = callback.data.split("_")[1]
    db.set_user_lang(callback.from_user.id, new_lang)
    await callback.message.answer(f"Success! Press /start")
    await callback.answer()

async def main():
    asyncio.create_task(run_web_server())
    db.init_db()
    await set_main_menu(bot)
    scheduler.start()
    
    # ЗАПУСКАЕМ ВЕБ-СЕРВЕР ДЛЯ RENDER
    asyncio.create_task(start_web_server())
    
    # ЗАПУСКАЕМ БОТА
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())