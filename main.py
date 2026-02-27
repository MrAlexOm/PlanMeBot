import os
import asyncio
import logging
import aiohttp
import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# Загрузка переменных окружения из .env файла
from dotenv import load_dotenv
load_dotenv()

# Импорты для работы с БД
from database import init_db, UserRepository, ReminderRepository
from models import User, Reminder
from sqlalchemy.ext.asyncio import AsyncSession
# Импорты для сообщений, логирования и middleware
from messages import MESSAGES, LANGUAGE_NAMES
from logger_config import setup_logging
from database_middleware import create_database_middleware
from api_logger import api_logger, bot_logger, log_execution_time

# --- НАСТРОЙКИ ---
# Приоритет: переменные окружения (.env) → config.py
API_TOKEN = os.getenv("BOT_TOKEN") or "8465020533:AAGulNiI2bL_v0xlAAxpqhRfIXVaTsKWP1Y"
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY") or "35e352d2f970db63c4d5d7fe630e869c"

# Настройка логирования
logger = setup_logging()

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

# Регистрация middleware для БД
dp.update.middleware(create_database_middleware())

# --- СОСТОЯНИЯ (FSM) ---
class TaskStates(StatesGroup):
    waiting_for_note = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_city = State()


# --- ПОГОДА И КАЧЕСТВО ВОЗДУХА ---
@log_execution_time(logging.getLogger("weather"))
async def fetch_weather_data(city, lang):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang={lang}"
    
    # Логирование запроса
    api_logger.log_request(
        method="GET",
        url=url,
        params={"city": city, "units": "metric", "lang": lang}
    )
    
    start_time = time.time()
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                response_time = time.time() - start_time
                
                if resp.status != 200: 
                    api_logger.log_response(resp.status, response_time=response_time, url=url)
                    return None
                
                data = await resp.json()
                api_logger.log_response(resp.status, data, response_time, url)
                
                lat, lon = data['coord']['lat'], data['coord']['lon']
                tz_offset = data.get('timezone', 0)
                
                # Дополнительный запрос на качество воздуха
                air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}"
                
                api_logger.log_request(
                    method="GET",
                    url=air_url,
                    params={"lat": lat, "lon": lon}
                )
                
                air_start_time = time.time()
                
                async with session.get(air_url) as a_resp:
                    air_response_time = time.time() - air_start_time
                    
                    if a_resp.status != 200:
                        api_logger.log_response(a_resp.status, response_time=air_response_time, url=air_url)
                        # Продолжаем даже без данных о качестве воздуха
                        aqi_val = 1
                    else:
                        air_data = await a_resp.json()
                        api_logger.log_response(a_resp.status, air_data, air_response_time, air_url)
                        aqi_val = air_data['list'][0]['main']['aqi']
                    
                    aqi_map = {1: "Excellent", 2: "Good", 3: "Fair", 4: "Poor", 5: "Very Poor"}
                
                return {
                    'temp': data['main']['temp'],
                    'desc': data['weather'][0]['description'],
                    'aqi': aqi_map.get(aqi_val, "N/A"),
                    'tz_offset': tz_offset
                }
                
    except Exception as e:
        response_time = time.time() - start_time
        api_logger.log_error(e, f"Weather API request failed for city: {city}")
        return None

async def send_scheduled_reminder(chat_id, note, city, lang):
    """Отправка запланированного напоминания с логированием"""
    try:
        w = await fetch_weather_data(city, lang)
        if w:
            text = MESSAGES[lang]['reminder_text'].format(
                note=note, city=city, temp=w['temp'], desc=w['desc'], aqi=w['aqi']
            )
        else:
            text = f"🔔 {note}\n(Weather data for {city} unavailable)"
        
        await bot.send_message(chat_id, text)
        
        # Логируем успешную отправку
        bot_logger.log_reminder_sent(chat_id, 0, True)  # reminder_id=0 для scheduled
        
    except Exception as e:
        # Логируем ошибку отправки
        logger.error(f"Failed to send reminder to {chat_id}: {e}")
        bot_logger.log_reminder_sent(chat_id, 0, False)

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton(text="English 🇺🇸", callback_data="lang_en")],
        [InlineKeyboardButton(text="Italiano 🇮🇹", callback_data="lang_it")]
    ])
    await message.answer("Choose language / Выберите язык / Scegli la lingua:", reply_markup=kb)

@dp.callback_query(F.data.startswith("lang_"))
async def select_lang(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    lang = callback.data.split("_")[-1]
    user_id = callback.from_user.id
    
    # Получаем текущий язык для логирования
    old_user = await UserRepository.get_by_id(session, user_id)
    old_lang = old_user.lang if old_user else 'en'
    
    await state.update_data(lang=lang)
    
    # Сохраняем язык в БД через репозиторий
    await UserRepository.set_lang(session, user_id, lang)
    
    # Логируем смену языка
    bot_logger.log_language_change(user_id, old_lang, lang)
    
    # Главное меню с кнопкой Задачи
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MESSAGES[lang]['btn_task'])]], 
        resize_keyboard=True
    )
    await callback.message.answer(MESSAGES[lang]['main_menu'], reply_markup=kb)
    await callback.answer()

@dp.message(F.text.in_({"📅 Задачи", "📅 Tasks", "📅 Compiti"}))
async def start_task_creation(message: types.Message, state: FSMContext, session: AsyncSession):
    # Получаем или создаем пользователя через репозиторий
    user = await UserRepository.get_or_create(session, message.from_user.id)
    lang = user.lang
    
    await state.update_data(lang=lang)
    await state.set_state(TaskStates.waiting_for_note)
    await message.answer(MESSAGES[lang]['ask_note'], reply_markup=types.ReplyKeyboardRemove())

@dp.message(TaskStates.waiting_for_note)
async def get_note(message: types.Message, state: FSMContext):
    await state.update_data(note=message.text)
    data = await state.get_data()
    lang = data['lang']
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=MESSAGES[lang]['today']), KeyboardButton(text=MESSAGES[lang]['tomorrow'])],
        [KeyboardButton(text=MESSAGES[lang]['after'])]
    ], resize_keyboard=True)
    
    await state.set_state(TaskStates.waiting_for_date)
    await message.answer(MESSAGES[lang]['ask_date'], reply_markup=kb)

@dp.message(TaskStates.waiting_for_date)
async def get_date(message: types.Message, state: FSMContext):
    await state.update_data(date_text=message.text)
    data = await state.get_data()
    await state.set_state(TaskStates.waiting_for_time)
    await message.answer(MESSAGES[data['lang']]['ask_time'], reply_markup=types.ReplyKeyboardRemove())

@dp.message(TaskStates.waiting_for_time)
async def get_time(message: types.Message, state: FSMContext):
    await state.update_data(time_text=message.text)
    data = await state.get_data()
    await state.set_state(TaskStates.waiting_for_city)
    await message.answer(MESSAGES[data['lang']]['ask_city'])

@dp.message(TaskStates.waiting_for_city)
async def get_city_and_finish(message: types.Message, state: FSMContext, session: AsyncSession):
    city = message.text
    data = await state.get_data()
    lang = data['lang']

    # Извлекаем выбранные дату и время
    date_text = data.get('date_text')
    time_text = data.get('time_text')

    # Загружаем данные по погоде, чтобы получить tz_offset города
    weather = await fetch_weather_data(city, lang)
    if not weather:
        # Локализованные сообщения об ошибке города
        await message.answer(MESSAGES[lang]['error_city'])
        return

    tz_offset = int(weather.get('tz_offset', 0))  # seconds

    # Текущее время в выбранном городе: UTC now + tz_offset
    utc_now = datetime.utcnow()
    local_now = utc_now + timedelta(seconds=tz_offset)

    # Нормализуем ключевые слова по языкам
    today_aliases = {MESSAGES['ru']['today'], MESSAGES['en']['today'], MESSAGES['it']['today'], 'Сегодня', 'Today', 'Oggi'}
    tomorrow_aliases = {MESSAGES['ru']['tomorrow'], MESSAGES['en']['tomorrow'], MESSAGES['it']['tomorrow'], 'Завтра', 'Tomorrow', 'Domani'}
    after_aliases = {MESSAGES['ru']['after'], MESSAGES['en']['after'], MESSAGES['it']['after'], 'Послезавтра', 'Day after tomorrow', 'Dopodomani', 'Day after'}

    # Определяем локальную дату пользователя
    base_date = local_now.date()
    if date_text in today_aliases:
        target_date = base_date
    elif date_text in tomorrow_aliases:
        target_date = base_date + timedelta(days=1)
    elif date_text in after_aliases:
        target_date = base_date + timedelta(days=2)
    else:
        await message.answer(MESSAGES[lang]['error_date'])
        return

    # Парсим время HH:MM
    try:
        hour_min = time_text.strip()
        parts = hour_min.split(":")
        if len(parts) != 2:
            raise ValueError("Time must be HH:MM")
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Time out of range")
    except Exception:
        await message.answer(MESSAGES[lang]['error_time'])
        return

    # Собираем локальное datetime в выбранном городе
    local_target = datetime(year=target_date.year, month=target_date.month, day=target_date.day, hour=hour, minute=minute)

    # Если локальное время уже прошло — переносим на следующий день
    if local_target <= local_now:
        local_target = local_target + timedelta(days=1)

    # Конверт��руем локальное время в UTC для планировщика: local - tz_offset
    remind_at_utc = local_target - timedelta(seconds=tz_offset)

    # Создаем напоминание в БД через репозиторий
    reminder = await ReminderRepository.create(
        session,
        user_id=message.from_user.id,
        task_text=data['note'],
        remind_at=remind_at_utc,
        city=city
    )
    
    # Логируем создание напоминания
    bot_logger.log_reminder_created(
        user_id=message.from_user.id,
        reminder_id=reminder.id,
        task_text=data['note'],
        remind_at=remind_at_utc.isoformat()
    )

    # Планируем задачу в UTC
    scheduler.add_job(
        send_scheduled_reminder,
        'date',
        run_date=remind_at_utc,
        args=[message.chat.id, data['note'], city, lang]
    )

    await message.answer(MESSAGES[lang]['confirm'])
    await state.clear()

# --- RENDER SERVER (Health Check) ---
async def handle(request): 
    return web.Response(text="PlanMe Bot is Live and Healthy")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()

# --- ЗАПУСК ---
async def main():
    # Инициализация БД
    await init_db()
    logger.info("Database initialized")
    
    # Start the health-check web server before entering the polling loop
    asyncio.create_task(start_web_server())
    scheduler.start()
    logger.info("Bot started successfully")

    # Survival loop for polling to auto-recover from transient failures
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(5)
            continue
        # If polling exits cleanly, break to avoid tight loop
        break

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")