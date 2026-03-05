import os
import asyncio
import logging
import aiohttp
import time
import re
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy import create_engine
from aiohttp import web
from aiogram3_calendar import SimpleCalendar
from aiogram3_calendar.calendar_types import SimpleCalendarCallback
from typing import Optional

# Constants for UX limits
MAX_TASKS = 30
TASKS_PER_PAGE = 5

# Загрузка переменных окружения из .env файла
from dotenv import load_dotenv
load_dotenv()

# Импорты для работы с БД
from database import init_db, UserRepository, ReminderRepository, AsyncSessionLocal
from models import User, Reminder
from sqlalchemy.ext.asyncio import AsyncSession
# Импорты для сообщений, логирования и middleware
from messages import MESSAGES, LANGUAGE_NAMES
from logger_config import setup_logging
from database_middleware import create_database_middleware
from api_logger import api_logger, bot_logger, log_execution_time
from nlp_engine import parse_task

# --- НАСТРОЙКИ ---
# Загрузка токенов из .env файла (НИКОГДА не храните токены в коде!)
API_TOKEN = os.getenv("BOT_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# Проверка наличия токенов
if not API_TOKEN:
    raise ValueError("BOT_TOKEN не найден! Создайте .env файл с вашим токеном.")
if not WEATHER_API_KEY:
    raise ValueError("WEATHER_API_KEY не найден! Создайте .env файл с вашим API ключом.")

# Настройка логирования
logger = setup_logging()

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Настройка команд меню бота
async def set_bot_commands():
    """Устанавливает команды меню бота с локализацией"""
    from aiogram.types import BotCommand
    
    # Команды для разных языков
    commands = {
        'ru': [
            BotCommand(command="/start", description="Перезапуск / Главное меню"),
            BotCommand(command="/help", description="Помощь"),
            BotCommand(command="/city", description="Изменить город"),
            BotCommand(command="/birthday", description="Изменить дату рождения"),
            BotCommand(command="/setcity", description="Быстро установить город"),
            BotCommand(command="/list", description="Список активных задач"),
        ],
        'en': [
            BotCommand(command="/start", description="Restart / Main menu"),
            BotCommand(command="/help", description="Help"),
            BotCommand(command="/city", description="Change city"),
            BotCommand(command="/birthday", description="Change birth date"),
            BotCommand(command="/setcity", description="Quick set city"),
            BotCommand(command="/list", description="Active tasks list"),
        ],
        'it': [
            BotCommand(command="/start", description="Riavvia / Menu principale"),
            BotCommand(command="/help", description="Aiuto"),
            BotCommand(command="/city", description="Cambia città"),
            BotCommand(command="/birthday", description="Cambia data di nascita"),
            BotCommand(command="/setcity", description="Imposta città velocemente"),
            BotCommand(command="/list", description="Elenco attività attive"),
        ]
    }
    
    # Устанавливаем команды для всех языков (по умолчанию английские)
    await bot.set_my_commands(commands['en'])
    logger.info("Bot menu commands set successfully")

# Настройка APScheduler с SQLAlchemyJobStore для persistent storage
jobstores = {
    'default': SQLAlchemyJobStore(url='sqlite:///scheduler.db')
}
scheduler = AsyncIOScheduler(timezone='UTC', jobstores=jobstores)
logger.info("Scheduler initialized with SQLAlchemyJobStore (persistent storage)")

# Настройка для обработки пропущенных задач (когда бот был офлайн)
# Увеличиваем время милости до 2 часов и добавляем coalescing
scheduler.configure(coalesce=True, misfire_grace_time=7200)  # 2 часа в секундах
logger.info("Scheduler configured with 2-hour misfire grace time and job coalescing")

# --- Вспомогательные функции ---
def get_main_keyboard(lang: str):
    """Возвращает главное меню клавиатуры для указанного языка"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
             KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
            [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
        ], 
        resize_keyboard=True
    )

# --- ЛОКАЛЬНЫЙ ПАРСИНГ RECURRENCE ---
def parse_recurrence_from_text(text: str) -> Optional[str]:
    """Извлекает тип повторения из текста через RegEx"""
    text_lower = text.lower()
    
    # Ежедневно / каждый день / daily
    daily_patterns = [
        r'каждый\s+день',
        r'ежедневно',
        r'ежедневное',
        r'every\s+day',
        r'daily',
        r'ogni\s+giorno',
        r'quotidiano'
    ]
    for pattern in daily_patterns:
        if re.search(pattern, text_lower):
            return 'daily'
    
    # По будням / weekdays
    weekdays_patterns = [
        r'по\s+будням',
        r'будни',
        r'на\s+рабочие\s+дни',
        r'weekdays',
        r'feriali',
        r'lun-ven',
        r'mon-fri'
    ]
    for pattern in weekdays_patterns:
        if re.search(pattern, text_lower):
            return 'weekdays'
    
    # Еженедельно / каждую неделю / weekly
    weekly_patterns = [
        r'каждую\s+неделю',
        r'еженедельно',
        r'every\s+week',
        r'weekly',
        r'ogni\s+settimana',
        r'settimanale'
    ]
    for pattern in weekly_patterns:
        if re.search(pattern, text_lower):
            return 'weekly'
    
    return None


def clean_recurrence_keywords(text: str, recurrence: Optional[str]) -> str:
    """Удаляет ключевые слова повторения из текста"""
    if not recurrence:
        return text
    
    patterns = []
    if recurrence == 'daily':
        patterns = [
            r'каждый\s+день',
            r'ежедневно',
            r'every\s+day',
            r'daily',
            r'ogni\s+giorno',
            r'quotidiano'
        ]
    elif recurrence == 'weekdays':
        patterns = [
            r'по\s+будням',
            r'будни',
            r'на\s+рабочие\s+дни',
            r'weekdays',
            r'feriali',
            r'lun-ven',
            r'mon-fri'
        ]
    elif recurrence == 'weekly':
        patterns = [
            r'каждую\s+неделю',
            r'еженедельно',
            r'every\s+week',
            r'weekly',
            r'ogni\s+settimana',
            r'settimanale'
        ]
    
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

# --- ЛЕЙБЛЫ ДЛЯ КАЛЕНДАРЯ ---
# Важно: строго задаем лейблы, чтобы не зависеть от системных локалей
CALENDAR_LABLES = {
    'ru': {
        'days_names': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
        'months_names': ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']
    },
    'en': {
        'days_names': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'months_names': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    },
    'it': {
        'days_names': ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'],
        'months_names': ['Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu', 'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic']
    }
}

# Регистрация middleware для БД
dp.update.middleware(create_database_middleware())

# --- СОСТОЯНИЯ (FSM) ---
class TaskStates(StatesGroup):
    waiting_for_note = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_city = State()
    waiting_for_birthdate = State()
    waiting_for_recurrence = State()


# --- CALLBACK ХЕНДЛЕР ДЛЯ ВЫБОРА ДАТЫ В КАЛЕНДАРЕ ---
@dp.callback_query(SimpleCalendarCallback.filter())
async def process_simple_calendar(callback_query: types.CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext):
    # Используем SimpleCalendar для обработки нажатия
    calendar = SimpleCalendar()
    # Подтягиваем лейблы снова, чтобы календарь при перелистывании месяцев не "слетел" на английский
    data = await state.get_data()
    lang = data.get('lang', 'ru')
    labels = CALENDAR_LABLES.get(lang, CALENDAR_LABLES['en'])
    calendar.days_names = labels['days_names']
    calendar.months_names = labels['months_names']

    selected, date = await calendar.process_selection(callback_query, callback_data)

    if selected:
        await state.update_data(date=date.strftime("%d.%m.%Y"))  # Use 'date' key and DD.MM.YYYY format
        logging.info(f"DEBUG CALENDAR: Date saved to state: '{date.strftime('%d.%m.%Y')}'")
        await callback_query.message.edit_text(
            f"✅ {MESSAGES[lang]['date_selected']}: {date.strftime('%d.%m.%Y')}"
        )
        await state.set_state(TaskStates.waiting_for_time)
        await callback_query.message.answer(MESSAGES[lang]['enter_time'])


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

async def send_scheduled_reminder(chat_id, note, city, lang, reminder_id=None):
    """Отправка запланированного напоминания с логированием"""
    try:
        # Test logging
        logger.info(f"Sending reminder in {lang} for user {chat_id}")
        
        # Ensure we have a valid language
        if not lang or lang not in MESSAGES:
            lang = 'ru'
        
        # Resolve city for weather API
        weather_city = city
        if not weather_city or weather_city in ['UTC', '']:
            # Get user's default city from database
            async with AsyncSessionLocal() as session:
                user_city = await UserRepository.get_city(session, chat_id)
                weather_city = user_city if user_city and user_city not in ['UTC', ''] else 'Tbilisi'  # Real city instead of UTC
        
        logger.info(f"DEBUG WEATHER: Using city '{weather_city}' for weather API")
        
        w = await fetch_weather_data(weather_city, lang)
        if w:
            text = MESSAGES.get(lang, MESSAGES['ru']).get('reminder_text', "🔔 Reminder: {note}").format(
                note=note, city=weather_city, temp=w['temp'], desc=w['desc'], aqi=w['aqi']
            )
        else:
            # Localized fallback message
            fallback_msg = MESSAGES.get(lang, MESSAGES['ru']).get('reminder_no_weather', f"🔔 {note}\n(Weather data for {city} unavailable)")
            text = fallback_msg.format(note=note, city=weather_city)
        
        await bot.send_message(chat_id, text)
        
        # Mark reminder as completed if reminder_id is provided
        if reminder_id:
            async with AsyncSessionLocal() as session:
                await ReminderRepository.mark_completed(session, reminder_id)
        
        # Логируем успешную отправку
        bot_logger.log_reminder_sent(chat_id, reminder_id or 0, True)
        
    except Exception as e:
        # Handle specific Telegram errors
        if "Forbidden" in str(e) or "chat not found" in str(e).lower():
            logger.info(f"User {chat_id} has blocked the bot or chat not found")
            bot_logger.log_reminder_sent(chat_id, reminder_id or 0, False)
            # Don't re-raise this exception - it's expected behavior
            return
        else:
            # Log other errors
            logger.error(f"Failed to send reminder to {chat_id}: {e}")
            bot_logger.log_reminder_sent(chat_id, reminder_id or 0, False)
            raise

async def display_user_tasks(message_or_call, user_id: int, lang: str, session: AsyncSession):
    """Отображение активных задач пользователя"""
    # Получаем активные задачи
    tasks = await ReminderRepository.get_active_by_user(session, user_id)
    
    if not tasks:
        await message_or_call.answer(MESSAGES[lang]['no_active_tasks'])
        return
    
    # Формируем список задач
    task_list = []
    for i, task in enumerate(tasks, 1):
        # Конвертируем UTC время в локальное
        utc_time = task.remind_at
        tz_offset = 0  # По умолчанию
        
        # Пытаемся получить tz_offset из погоды города
        if task.city:
            weather = await fetch_weather_data(task.city, lang)
            if weather:
                tz_offset = weather.get('tz_offset', 0)
        
        # Конвертируем в локальное время
        local_time = utc_time + timedelta(seconds=tz_offset)
        
        # Форматируем время
        time_str = local_time.strftime("%H:%M")
        date_str = local_time.strftime("%d.%m")
        
        # Определяем иконку повторения
        recurrence_icons = {
            None: "🕐",
            'daily': "🔄",
            'weekdays': "📅",
            'weekly': "🗓"
        }
        recurrence_text = {
            None: "Один раз",
            'daily': "Ежедневно",
            'weekdays': "По будням",
            'weekly': "Еженедельно"
        }
        
        icon = recurrence_icons.get(task.recurrence, "🕐")
        repeat = recurrence_text.get(task.recurrence, "Один раз")
        
        # Формируем строку задачи
        task_line = f"{i}. {icon} {date_str} {time_str} - {task.task_text} ({repeat}) 🏙 {task.city}"
        
        # Создаем кнопку удаления
        delete_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Удалить", callback_data=f"delete_{task.id}")]
        ])
        
        task_list.append((task_line, delete_kb))
    
    # Отправляем задачи
    for task_text, keyboard in task_list:
        await message_or_call.answer(task_text, reply_markup=keyboard)

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton(text="English 🇺🇸", callback_data="lang_en")],
        [InlineKeyboardButton(text="Italiano 🇮🇹", callback_data="lang_it")]
    ])
    await message.answer("Choose language / Выберите язык / Scegli la lingua:", reply_markup=kb)

@dp.message(Command("list"))
async def cmd_list(message: types.Message, **data):
    """Обработчик команды /list для показа активных задач"""
    session = data.get("session")
    if not session:
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    
    # Получаем язык пользователя
    lang = await UserRepository.get_lang(session, user_id)
    
    # Показываем задачи
    await display_user_tasks(message, user_id, lang, session)

@dp.message(Command("city"))
async def cmd_city(message: types.Message, state: FSMContext, **data):
    """Обработчик команды /city для настройки города пользователя"""
    session = data.get("session")
    if not session:
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    await state.set_state(TaskStates.waiting_for_city)
    await state.update_data(lang=lang)
    
    await message.answer(
        MESSAGES.get(lang, MESSAGES['ru']).get('city_setup', 'Enter your city name:'),
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]],
            resize_keyboard=True
        )
    )

@dp.message(Command("setcity"))
async def cmd_setcity(message: types.Message, **data):
    """Простая команда для быстрой установки города: /setcity Тбилиси"""
    session = data.get("session")
    if not session:
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    # Extract city from command
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /setcity <название города>\nПример: /setcity Тбилиси")
        return
    
    city_name = parts[1].strip()
    
    try:
        await UserRepository.set_city(session, user_id, city_name)
        
        success_messages = {
            'ru': f"✅ Город установлен: {city_name}",
            'en': f"✅ City set: {city_name}",
            'it': f"✅ Città impostata: {city_name}"
        }
        
        await message.answer(success_messages.get(lang, f"✅ City set: {city_name}"))
        
    except Exception as e:
        await message.answer(f"Ошибка при сохранении города: {e}")

@dp.message(Command("birthday"))
async def cmd_birthday(message: types.Message, state: FSMContext, **data):
    """Команда для изменения даты рождения"""
    session = data.get("session")
    if not session:
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    # Устанавливаем состояние для ожидания даты рождения
    await state.set_state(TaskStates.waiting_for_birthdate)
    await state.update_data(lang=lang)
    
    birthday_messages = {
        'ru': "🎂 Введите вашу дату рождения в формате ДД.ММ.ГГГГ\nНапример: 15.04.1990",
        'en': "🎂 Enter your birth date in format DD.MM.YYYY\nFor example: 15.04.1990",
        'it': "🎂 Inserisci la tua data di nascita in formato GG.MM.AAAA\nPer esempio: 15.04.1990"
    }
    
    await message.answer(birthday_messages.get(lang, birthday_messages['ru']))

@dp.message(Command("help"))
async def cmd_help(message: types.Message, **data):
    """Команда помощи"""
    session = data.get("session")
    if not session:
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    help_messages = {
        'ru': """🤖 *PlanMeBOT - Помощь*

📅 *Создание задач:*
• Напишите: "Купить кофе в 18:00"
• Или: "Встреча завтра в 15:30"

🌤️ *Погода:*
• Установите город: /setcity Тбилиси
• Задачи будут включать погоду

🔮 *Гороскоп:*
• Установите дату рождения: /birthday ДД.ММ.ГГГГ
• Нажмите кнопку "🔮 Гороскоп"

📋 *Управление:*
• /list - активные задачи
• /city - изменить город
• /birthday - изменить дату рождения

⏰ *Формат времени:* ЧЧ:ММ (например, 18:30)""",
        
        'en': """🤖 *PlanMeBOT - Help*

📅 *Task Creation:*
• Write: "Buy coffee at 18:00"
• Or: "Meeting tomorrow at 15:30"

🌤️ *Weather:*
• Set city: /setcity Tbilisi
• Tasks will include weather

🔮 *Horoscope:*
• Set birth date: /birthday DD.MM.YYYY
• Press "🔮 Horoscope" button

📋 *Management:*
• /list - active tasks
• /city - change city
• /birthday - change birth date

⏰ *Time format:* HH:MM (e.g., 18:30)""",
        
        'it': """🤖 *PlanMeBOT - Aiuto*

📅 *Creazione Attività:*
• Scrivi: "Comprare caffè alle 18:00"
• O: "Riunione domani alle 15:30"

🌤️ *Meteo:*
• Imposta città: /setcity Tbilisi
• Le attività includeranno il meteo

🔮 *Oroscopo:*
• Imposta data di nascita: /birthday GG.MM.AAAA
• Premi il pulsante "🔮 Oroscopo"

📋 *Gestione:*
• /list - attività attive
• /city - cambia città
• /birthday - cambia data di nascita

⏰ *Formato ora:* HH:MM (es. 18:30)"""
    }
    
    await message.answer(help_messages.get(lang, help_messages['ru']), parse_mode="Markdown")

# --- ГЛОБАЛЬНЫЙ ХЕНДЛЕР ОТМЕНЫ ---
@dp.message(F.text.casefold() == "отмена")
@dp.message(Command("cancel"))
async def cancel_handler(message: types.Message, state: FSMContext):
    """Обработчик отмены любого состояния"""
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=ReplyKeyboardRemove())

@dp.message(F.text.in_({
    MESSAGES['ru']['btn_my_tasks'], 
    MESSAGES['en']['btn_my_tasks'], 
    MESSAGES['it']['btn_my_tasks']
}))
async def btn_my_tasks(message: types.Message, **data):
    """Обработчик кнопки «Мои задачи»"""
    session = data.get("session")
    if not session:
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    
    # Получаем язык пользователя
    lang = await UserRepository.get_lang(session, user_id)
    
    # Показываем задачи
    await display_user_tasks(message, user_id, lang, session)

@dp.callback_query(F.data.startswith("lang_"))
async def select_lang(callback: types.CallbackQuery, state: FSMContext):
    # Получаем session или создаем новую
    session = None
    try:
        # Пробуем получить session из middleware (если есть)
        from aiogram.dispatcher.event.handler import HandlerObject
        # Если session не передана, создаем свою
        async with AsyncSessionLocal() as session:
            print(f">>> select_lang: создана новая сессия {session}")
            
            lang = callback.data.split("_")[-1]
            user_id = callback.from_user.id
            print(f">>> lang={lang}, user_id={user_id}")
            
            # Получаем текущий язык для логирования
            old_user = await UserRepository.get_by_id(session, user_id)
            old_lang = old_user.lang if old_user else 'en'
            
            await state.update_data(lang=lang)
            
            # Сохраняем язык в БД через репозиторий
            await UserRepository.set_lang(session, user_id, lang)
            
            # Проверяем наличие города и таймзоны для онбординга
            user_city = await UserRepository.get_city(session, user_id)
            user_timezone = await UserRepository.get_timezone(session, user_id)
            
            # Логируем смену языка
            bot_logger.log_language_change(user_id, old_lang, lang)
            
            # Умный онбординг - проверяем настройки
            if not user_city or user_city in ['UTC', '']:
                # Устанавливаем состояние для ожидания города
                await state.set_state(TaskStates.waiting_for_city)
                await state.update_data(lang=lang)
                
                # Запрашиваем город для точной работы
                onboarding_messages = {
                    'ru': "👋 Добро пожаловать! Для точной работы напоминаний и погоды, пожалуйста, укажите свой город (напишите его название).",
                    'en': "👋 Welcome! For accurate reminders and weather, please specify your city (just type its name).",
                    'it': "👋 Benvenuto! Per promemorie e meteo accurate, specifica la tua città (scrivi il suo nome)."
                }
                
                await callback.message.answer(onboarding_messages.get(lang, onboarding_messages['ru']))
                
                # Показываем примеры городов
                city_examples = {
                    'ru': "Например: Тбилиси, Москва, Анталья, Батуми",
                    'en': "For example: Tbilisi, Moscow, Antalya, Batumi", 
                    'it': "Per esempio: Tbilisi, Mosca, Antalya, Batumi"
                }
                
                await callback.message.answer(city_examples.get(lang, city_examples['ru']))
            else:
                # Главное меню с кнопками Задачи, Мои задачи и Гороскоп
                kb = ReplyKeyboardMarkup(
                    keyboard=[
                        [KeyboardButton(text=MESSAGES[lang]['btn_task']), KeyboardButton(text=MESSAGES[lang]['btn_my_tasks'])],
                        [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
                    ], 
                    resize_keyboard=True
                )
                await callback.message.answer(MESSAGES[lang]['main_menu'], reply_markup=kb)
            await callback.answer()
            print(f">>> select_lang: УСПЕШНО ЗАВЕРШЕН")
            
    except Exception as e:
        print(f">>> select_lang ОШИБКА: {e}")
        import traceback
        print(f">>> TRACEBACK: {traceback.format_exc()}")
        await callback.message.answer(f"Ошибка при сохранении языка: {e}")
        await callback.answer()

@dp.message(F.text.in_({"📅 Задачи", "📅 Tasks", "📅 Compiti"}))
async def start_task_creation(message: types.Message, state: FSMContext, **data):
    # Получаем session из data
    session = data.get("session")
    if not session:
        logger.error("=== start_task_creation: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    # Получаем или создаем пользователя через репозиторий
    user = await UserRepository.get_or_create(session, message.from_user.id)
    lang = user.lang
    
    await state.update_data(lang=lang)
    await state.set_state(TaskStates.waiting_for_note)
    await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('ask_note', 'Enter your note:'), reply_markup=ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]],
        resize_keyboard=True
    ))

# --- ХЕНДЛЕР ДЛЯ ПРОСМОТРА МОИХ ЗАДАЧ ---
@dp.message(F.text.in_({"🗂 Мои задачи", "🗂 My Tasks", "🗂 I miei compiti"}))
async def show_my_tasks(message: types.Message, **data):
    """Показывает список активных задач пользователя с пагинацией"""
    session = data.get("session")
    if not session:
        logger.error("=== show_my_tasks: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return

    user_id = message.from_user.id

    # Получаем язык пользователя
    lang = await UserRepository.get_lang(session, user_id)
    
    # Получаем город пользователя
    user_city = await UserRepository.get_city(session, user_id)
    city_display = user_city if user_city else 'UTC'

    # Получаем активные задачи (только будущие) с пагинацией
    page = 1  # Start with first page
    tasks = await ReminderRepository.get_user_reminders_paginated(
        session, user_id, active_only=True, future_only=True, page=page, per_page=TASKS_PER_PAGE
    )
    
    # Get total count for pagination
    total_tasks = await ReminderRepository.get_active_count(session, user_id)
    total_pages = (total_tasks + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE  # Ceiling division

    # Логируем просмотр задач
    bot_logger.log_user_action(user_id, "view_tasks", f"Found {total_tasks} future tasks, showing page {page}")

    if not tasks:
        # Добавляем кнопку смены города даже если нет задач
        change_city_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_change_city', '📍 Change City'), callback_data="start_city_change")]
        ])
        city_info = MESSAGES.get(lang, MESSAGES['ru']).get('current_city_info', 'Current city: {city} ({timezone})').format(city=city_display, timezone='UTC')
        await message.answer(f"{city_info}\n\n{MESSAGES.get(lang, MESSAGES['ru']).get('no_active_tasks', 'No active tasks')}", reply_markup=change_city_kb)
        return

    # Добавляем информацию о городе
    city_info = MESSAGES.get(lang, MESSAGES['ru']).get('current_city_info', 'Current city: {city} ({timezone})').format(city=city_display, timezone='UTC')
    
    # Отправляем заголовок с информацией о городе и пагинацией
    page_info = MESSAGES.get(lang, MESSAGES['ru']).get('page_info', 'Page {current} of {total}').format(current=page, total=total_pages)
    await message.answer(f"*Ваши активные задачи ({total_tasks}):*\n\n{city_info}\n{page_info}", parse_mode="Markdown")

    # Отправляем каждую задачу с inline-кнопками
    for task in tasks:
        # Форматируем дату и время
        task_date = task.remind_at.strftime("%d.%m.%Y")
        task_time = task.remind_at.strftime("%H:%M")

        task_text = MESSAGES.get(lang, MESSAGES['ru']).get('task_item', "📝 {task}\n📅 {date}\n⏰ {time}").format(
            task=task.task_text,
            date=task_date,
            time=task_time
        )

        # Создаем inline-кнопки для задачи
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅", callback_data=f"done_{task.id}"),
                InlineKeyboardButton(text="❌", callback_data=f"delete_{task.id}")
            ]
        ])

        await message.answer(task_text, reply_markup=kb)
    
    # Создаем клавиатуру пагинации и управления городом
    pagination_buttons = []
    
    # Previous page button
    if page > 1:
        pagination_buttons.append([InlineKeyboardButton(
            text=MESSAGES.get(lang, MESSAGES['ru']).get('previous_page', '← Back'), 
            callback_data=f"tasks_page_{page-1}"
        )])
    
    # Next page button
    if page < total_pages:
        pagination_buttons.append([InlineKeyboardButton(
            text=MESSAGES.get(lang, MESSAGES['ru']).get('next_page', 'Next →'), 
            callback_data=f"tasks_page_{page+1}"
        )])
    
    # Add city management button
    pagination_buttons.append([InlineKeyboardButton(
        text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_change_city', '📍 Change City'), 
        callback_data="start_city_change"
    )])
    
    pagination_kb = InlineKeyboardMarkup(inline_keyboard=pagination_buttons)
    await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('city_management', 'City Management:'), reply_markup=pagination_kb)

# --- CALLBACK ХЕНДЛЕР ДЛЯ СМЕНЫ ГОРОДА ---
@dp.callback_query(F.data == "start_city_change")
async def change_city_callback(callback: types.CallbackQuery, state: FSMContext, **data):
    """Обрабатывает нажатие на кнопку смены города"""
    session = data.get("session")
    if not session:
        await callback.answer("Ошибка: сессия не найдена", show_alert=True)
        return
    
    user_id = callback.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    # Устанавливаем состояние ожидания города
    await state.set_state(TaskStates.waiting_for_city)
    await state.update_data(lang=lang)
    
    # Отправляем запрос на ввод города с кнопкой отмены
    cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=cancel_text)]],
        resize_keyboard=True
    )
    
    ask_city_msg = MESSAGES.get(lang, MESSAGES['ru']).get('ask_city', 'In which city should I check the weather?')
    await callback.message.answer(ask_city_msg, reply_markup=kb)
    await callback.answer()

# --- CALLBACK ХЕНДЛЕР ДЛЯ ПАГИНАЦИИ ЗАДАЧ ---
@dp.callback_query(F.data.startswith("tasks_page_"))
async def tasks_pagination_callback(callback: types.CallbackQuery, **data):
    """Обрабатывает пагинацию списка задач"""
    session = data.get("session")
    if not session:
        await callback.answer("Ошибка: сессия не найдена", show_alert=True)
        return
    
    try:
        # Extract page number from callback data
        page = int(callback.data.split("_")[2])
        user_id = callback.from_user.id
        lang = await UserRepository.get_lang(session, user_id)
        
        # Get city info
        user_city = await UserRepository.get_city(session, user_id)
        city_display = user_city if user_city else 'UTC'
        
        # Get tasks for this page
        tasks = await ReminderRepository.get_user_reminders_paginated(
            session, user_id, active_only=True, future_only=True, page=page, per_page=TASKS_PER_PAGE
        )
        
        # Get total count for pagination
        total_tasks = await ReminderRepository.get_active_count(session, user_id)
        total_pages = (total_tasks + TASKS_PER_PAGE - 1) // TASKS_PER_PAGE
        
        # Delete previous messages and send new ones
        await callback.message.delete()
        
        # Send header with city info and pagination
        city_info = MESSAGES.get(lang, MESSAGES['ru']).get('current_city_info', 'Current city: {city} ({timezone})').format(city=city_display, timezone='UTC')
        page_info = MESSAGES.get(lang, MESSAGES['ru']).get('page_info', 'Page {current} of {total}').format(current=page, total=total_pages)
        await callback.message.answer(f"*Ваши активные задачи ({total_tasks}):*\n\n{city_info}\n{page_info}", parse_mode="Markdown")
        
        # Send tasks
        for task in tasks:
            task_date = task.remind_at.strftime("%d.%m.%Y")
            task_time = task.remind_at.strftime("%H:%M")
            
            task_text = MESSAGES.get(lang, MESSAGES['ru']).get('task_item', "📝 {task}\n📅 {date}\n⏰ {time}").format(
                task=task.task_text,
                date=task_date,
                time=task_time
            )
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅", callback_data=f"done_{task.id}"),
                    InlineKeyboardButton(text="❌", callback_data=f"delete_{task.id}")
                ]
            ])
            
            await callback.message.answer(task_text, reply_markup=kb)
        
        # Create pagination keyboard
        pagination_buttons = []
        
        if page > 1:
            pagination_buttons.append([InlineKeyboardButton(
                text=MESSAGES.get(lang, MESSAGES['ru']).get('previous_page', '← Back'), 
                callback_data=f"tasks_page_{page-1}"
            )])
        
        if page < total_pages:
            pagination_buttons.append([InlineKeyboardButton(
                text=MESSAGES.get(lang, MESSAGES['ru']).get('next_page', 'Next →'), 
                callback_data=f"tasks_page_{page+1}"
            )])
        
        pagination_buttons.append([InlineKeyboardButton(
            text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_change_city', '📍 Change City'), 
            callback_data="start_city_change"
        )])
        
        pagination_kb = InlineKeyboardMarkup(inline_keyboard=pagination_buttons)
        await callback.message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('city_management', 'City Management:'), reply_markup=pagination_kb)
        
        await callback.answer()
        
    except (ValueError, IndexError) as e:
        logger.error(f"Pagination error: {e}")
        await callback.answer("Ошибка пагинации", show_alert=True)
    except Exception as e:
        logger.error(f"Unexpected pagination error: {e}")
        await message.answer("Произошла ошибка", show_alert=True)

# --- ХЕНДЛЕР ДЛЯ УСТАНОВКИ ДАТЫ РОЖДЕНИЯ ---
@dp.message(F.text.startswith("/birthdate"))
async def handle_birthdate(message: types.Message, **data):
    """Обрабатывает команду установки даты рождения"""
    session = data.get("session")
    if not session:
        logger.error("=== handle_birthdate: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    # Извлекаем дату из команды
    try:
        birth_date = message.text.split()[1] if len(message.text.split()) > 1 else None
        
        if not birth_date:
            # Запрашиваем дату рождения
            await message.answer(
                MESSAGES.get(lang, MESSAGES['ru']).get('ask_birthdate', 'Пожалуйста, введите вашу дату рождения в формате ДД.ММ.ГГГГ (например: 15.04.1990)'),
                reply_markup=ReplyKeyboardMarkup(
                    keyboard=[[KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]],
                    resize_keyboard=True
                )
            )
            return
        
        # Проверяем формат даты
        from datetime import datetime
        try:
            datetime.strptime(birth_date, '%d.%m.%Y')
        except ValueError:
            await message.answer(
                MESSAGES.get(lang, MESSAGES['ru']).get('invalid_birthdate', 'Неверный формат даты. Используйте ДД.ММ.ГГГГ (например: 15.04.1990)')
            )
            return
        
        # Сохраняем дату рождения
        await UserRepository.set_birth_date(session, user_id, birth_date)
        
        # Определяем знак зодиака
        from utils import get_zodiac_sign, get_zodiac_sign_en, get_zodiac_sign_it
        if lang == 'ru':
            zodiac_sign = get_zodiac_sign(birth_date)
        elif lang == 'en':
            zodiac_sign = get_zodiac_sign_en(birth_date)
        elif lang == 'it':
            zodiac_sign = get_zodiac_sign_it(birth_date)
        
        success_msg = MESSAGES.get(lang, MESSAGES['ru']).get('birthdate_saved', '✅ Дата рождения сохранена! Ваш знак зодиака: {zodiac}').format(zodiac=zodiac_sign)
        await message.answer(success_msg)
        
    except IndexError:
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('ask_birthdate', 'Пожалуйста, введите вашу дату рождения в формате ДД.ММ.ГГГГ (например: 15.04.1990)')
        )
    except Exception as e:
        logger.error(f"Error setting birth date: {e}")
        await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('error_general', 'Произошла ошибка. Попробуйте еще раз.'))

# --- ХЕНДЛЕР ДЛЯ ГОРОСКОПА ---
@dp.message(F.text.in_({"🔮 Гороскоп", "🔮 Horoscope", "🔮 Oroscopo"}))
async def handle_horoscope(message: types.Message, state: FSMContext, **data):
    """Обрабатывает запрос гороскопа с ограничением 1 раз в сутки"""
    session = data.get("session")
    if not session:
        logger.error("=== handle_horoscope: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    try:
        # Получаем текущую дату
        from datetime import date
        today = date.today()
        
        # Проверяем, получал ли пользователь гороскоп сегодня
        last_horoscope_date = await UserRepository.get_last_horoscope_date(session, user_id)
        
        if last_horoscope_date == today:
            # Пользователь уже получал гороскоп сегодня
            await message.answer(MESSAGES.get(lang, MESSAGES['ru'])['horoscope_limit'])
            return
        
        # Проверяем, есть ли дата рождения
        birth_date = await UserRepository.get_birth_date(session, user_id)
        
        if not birth_date:
            # Запрашиваем дату рождения
            await state.set_state(TaskStates.waiting_for_birthdate)
            await state.update_data(lang=lang)
            
            ask_birthdate_msg = MESSAGES.get(lang, MESSAGES['ru']).get('ask_birthdate', 'Пожалуйста, введите вашу дату рождения в формате ДД.ММ.ГГГГ (например: 15.04.1990)')
            cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
            
            kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=cancel_text)]],
                resize_keyboard=True
            )
            
            await message.answer(ask_birthdate_msg, reply_markup=kb)
            return
        
        # Генерируем гороскоп
        await generate_personalized_horoscope(message, session, user_id, lang, birth_date, state)
        
    except Exception as e:
        logger.error(f"Horoscope handler error: {e}")
        await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('horoscope_error', 'The stars are silent today... Try again later.'))

async def generate_personalized_horoscope(message: types.Message, session, user_id: int, lang: str, birth_date: str, state: FSMContext):
    """Генерирует персонализированный гороскоп"""
    from datetime import date
    from utils import get_zodiac_sign, get_zodiac_sign_en, get_zodiac_sign_it
    from nlp_engine import generate_horoscope
    
    # Определяем знак зодиака
    if lang == 'ru':
        zodiac_sign = get_zodiac_sign(birth_date)
    elif lang == 'en':
        zodiac_sign = get_zodiac_sign_en(birth_date)
    elif lang == 'it':
        zodiac_sign = get_zodiac_sign_it(birth_date)
    
    # Debug logging for date parsing
    logger.info(f"DEBUG HOROSCOPE: Birth date input: '{birth_date}' → Zodiac: '{zodiac_sign}'")
    
    # Получаем город пользователя
    user_city = await UserRepository.get_city(session, user_id)
    city_display = user_city if user_city else 'UTC'
    
    try:
        # Генерируем персонализированный гороскоп с новым форматом
        horoscope_text = await generate_horoscope(zodiac_sign, birth_date, city_display, lang)
        
        # Добавляем знак зодиака к сообщению
        horoscope_message = f"✨ Ваш гороскоп на сегодня ({zodiac_sign}):\n\n{horoscope_text}"
        
        # Отправляем гороскоп пользователю
        await message.answer(horoscope_message, parse_mode="HTML")
        
        # Обновляем дату последнего гороскопа
        today = date.today()
        await UserRepository.set_last_horoscope_date(session, user_id, today)
        
        # Показываем главное меню с вопросом "Что делаем дальше?"
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
                 KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
            ], 
            resize_keyboard=True
        )
        
        next_action_msg = {
            'ru': 'Что делаем дальше?',
            'en': 'What\'s next?',
            'it': 'Cosa facciamo dopo?'
        }
        
        await message.answer(next_action_msg.get(lang, next_action_msg['ru']), reply_markup=kb)
        
        # Очищаем состояние FSM
        await state.clear()
        
        logger.info(f"Horoscope generated for user {user_id} in {lang} with zodiac {zodiac_sign}")
        
    except Exception as horoscope_error:
        logging.error(f"Horoscope Error: {horoscope_error}")
        logging.error(f"Error type: {type(horoscope_error).__name__}")
        logging.error(f"Error details: {str(horoscope_error)}")
        
        # Check for rate limit error
        if "429" in str(horoscope_error) or "RESOURCE_EXHAUSTED" in str(horoscope_error) or "rate limit" in str(horoscope_error).lower():
            await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('ai_cooling_down', '🤖 The AI is cooling down. Please try again in a minute!'))
        else:
            # Показываем реальную ошибку для отладки
            error_message = f"⚠️ Ошибка генерации гороскопа: {str(horoscope_error)}"
            await message.answer(error_message)

# --- ХЕНДЛЕР ДЛЯ ВВОДА ДАТЫ РОЖДЕНИЯ ---
@dp.message(TaskStates.waiting_for_birthdate)
async def process_birthdate(message: types.Message, state: FSMContext, **data):
    """Обрабатывает ввод даты рождения для гороскопа"""
    session = data.get("session")
    if not session:
        logger.error("=== process_birthdate: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    birth_date_input = message.text.strip()
    
    # Получаем язык из состояния
    state_data = await state.get_data()
    lang = state_data.get('lang', 'ru')
    
    # Проверяем на отмену
    cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
    if birth_date_input == cancel_text:
        await state.clear()
        await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('welcome_back', '🏠 Главное меню. Что делаем?'), reply_markup=get_main_keyboard(lang))
        return
    
    # Валидация даты с помощью regex и datetime
    import re
    from datetime import datetime
    
    # Проверяем формат DD.MM.YYYY с regex
    date_pattern = r'^\d{2}\.\d{2}\.\d{4}$'
    if not re.match(date_pattern, birth_date_input):
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('invalid_birthdate', 'Неверный формат даты. Используйте ДД.ММ.ГГГГ (например: 15.04.1990)')
        )
        return
    
    # Проверяем, что дата реальная
    try:
        parsed_date = datetime.strptime(birth_date_input, '%d.%m.%Y')
        logger.info(f"DEBUG BIRTHDATE: Input '{birth_date_input}' → Parsed as {parsed_date.strftime('%d.%m.%Y')}")
        
        # Дополнительная проверка: дата не в будущем и не слишком старая
        today = datetime.now()
        if parsed_date > today:
            await message.answer(
                MESSAGES.get(lang, MESSAGES['ru']).get('invalid_birthdate', 'Дата рождения не может быть в будущем. Используйте ДД.ММ.ГГГГ (например: 15.04.1990)')
            )
            return
        
        # Проверяем, что возраст разумный (не старше 120 лет)
        min_date = today.replace(year=today.year - 120)
        if parsed_date < min_date:
            await message.answer(
                MESSAGES.get(lang, MESSAGES['ru']).get('invalid_birthdate', 'Дата рождения слишком давняя. Используйте ДД.ММ.ГГГГ (например: 15.04.1990)')
            )
            return
        
        # Сохраняем дату рождения
        await UserRepository.set_birth_date(session, user_id, birth_date_input)
        logger.info(f"Birth date saved for user {user_id}: {birth_date_input}")
        
        # Генерируем гороскоп
        await generate_personalized_horoscope(message, session, user_id, lang, birth_date_input, state)
        
        # Очищаем состояние
        await state.clear()
        
    except ValueError:
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('invalid_birthdate', 'Неверная дата. Используйте ДД.ММ.ГГГГ (например: 15.04.1990)')
        )
    except Exception as e:
        logger.error(f"Error processing birthdate: {e}")
        await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('error_general', 'Произошла ошибка. Попробуйте еще раз.'))

# --- CALLBACK ХЕНДЛЕРЫ ДЛЯ УПРАВЛЕНИЯ ЗАДАЧАМИ ---
@dp.callback_query(F.data.startswith("done_"))
async def task_done_callback(callback: types.CallbackQuery, **data):
    """Отмечает задачу как выполненную"""
    session = data.get("session")
    if not session:
        await callback.answer("Ошибка: сессия не найдена", show_alert=True)
        return
    
    # Получаем ID задачи из callback_data
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Получаем язык пользователя
    lang = await UserRepository.get_lang(session, user_id)
    
    # Получаем детали задачи перед отметкой
    task = await ReminderRepository.get_by_id(session, task_id)
    if not task:
        await callback.answer("❌ Задача не найдена", show_alert=True)
        return
    
    # Отправляем напоминание с погодой сразу (до отметки выполненным)
    try:
        w = await fetch_weather_data(task.city, lang)
        if w:
            text = MESSAGES[lang]['reminder_text'].format(
                note=task.task_text, city=task.city, temp=w['temp'], desc=w['desc'], aqi=w['aqi']
            )
        else:
            text = f"🔔 {task.task_text}\n(Данные о погоде недоступны)"
        
        await bot.send_message(user_id, text)
        bot_logger.log_reminder_sent(user_id, task_id, True)
    except Exception as e:
        logger.error(f"Failed to send immediate reminder for task {task_id}: {e}")
        bot_logger.log_reminder_sent(user_id, task_id, False)
    
    # Отмечаем задачу как выполненную
    success = await ReminderRepository.mark_completed(session, task_id)
    
    if success:
        # Удаляем job из планировщика
        job_id = f"reminder_{task_id}"
        try:
            scheduler.remove_job(job_id)
            logger.info(f"Removed job {job_id} from scheduler")
        except Exception as e:
            logger.warning(f"Could not remove job {job_id}: {e}")
        
        # Логируем действие
        bot_logger.log_user_action(user_id, "task_completed", f"Task {task_id} marked as done")
        
        # Обновляем сообщение
        await callback.message.edit_text(
            f"{callback.message.text}\n\n{MESSAGES[lang]['task_done']}",
            reply_markup=None
        )
        await callback.answer(MESSAGES[lang]['task_done'])
    else:
        await callback.answer("❌ Не удалось отметить задачу", show_alert=True)

@dp.callback_query(F.data.startswith("delete_"))
async def task_delete_callback(callback: types.CallbackQuery, **data):
    """Удаляет задачу"""
    session = data.get("session")
    if not session:
        await callback.answer("Ошибка: сессия не найдена", show_alert=True)
        return
    
    # Получаем ID задачи из callback_data
    task_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Получаем язык пользователя
    lang = await UserRepository.get_lang(session, user_id)
    
    # Удаляем job из планировщика ДО удаления из БД
    job_id = f"reminder_{task_id}"
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Removed job {job_id} from scheduler")
    except Exception as e:
        logger.warning(f"Could not remove job {job_id}: {e}")
    
    # Удаляем задачу из базы данных
    success = await ReminderRepository.delete(session, task_id, user_id)
    
    if success:
        # Логируем действие
        bot_logger.log_user_action(user_id, "task_deleted", f"Task {task_id} deleted")
        
        # Удаляем сообщение с задачей
        await callback.message.delete()
        await callback.answer(MESSAGES[lang]['task_deleted'])
    else:
        await callback.answer("❌ Не удалось удалить задачу", show_alert=True)

@dp.callback_query(SimpleCalendarCallback.filter())
async def process_simple_calendar(callback: types.CallbackQuery, callback_data: SimpleCalendarCallback, state: FSMContext):
    """Обработка выбора даты в календаре"""
    # Получаем язык пользователя из state
    data = await state.get_data()
    lang = data.get('lang', 'ru')
    
    # Подтягиваем лейблы для локализации
    labels = CALENDAR_LABELS.get(lang, CALENDAR_LABELS['en'])
    calendar = SimpleCalendar()
    calendar.days_names = labels['days_names']
    calendar.months_names = labels['months_names']
    
    selected, date = await calendar.process_selection(callback, callback_data)
    
    if selected:
        # Валидация даты - проверяем, что дата не в прошлом
        from datetime import datetime, date as date_type
        today = date_type.today()
        
        if date < today:
            # Дата в прошлом - показываем предупреждение
            warning_messages = {
                'ru': 'Нельзя выбрать прошедшую дату!',
                'en': 'Cannot select a past date!',
                'it': 'Non puoi selezionare una data passata!'
            }
            await callback.answer(text=warning_messages.get(lang, 'Нельзя выбрать прошедшую дату!'), show_alert=True)
            return
        
        # Сохраняем дату в FSM
        date_str = date.strftime("%d.%m.%Y")  # Используем формат ДД.ММ.ГГГГ
        await state.update_data(date=date_str)
        logging.info(f"DEBUG CALENDAR: Date saved to state: '{date_str}'")
        
        # Создаем кнопки быстрого выбора времени
        time_buttons = []
        time_options = ['09:00', '12:00', '15:00', '18:00', '21:00']
        
        for time_opt in time_options:
            time_buttons.append([InlineKeyboardButton(text=time_opt, callback_data=f"time_{time_opt}")])
        
        # Добавляем кнопку для ручного ввода времени
        manual_time_text = {
            'ru': '⌨️ Ввести время вручную',
            'en': '⌨️ Enter time manually',
            'it': '⌨️ Inserisci tempo manualmente'
        }
        time_buttons.append([InlineKeyboardButton(text=manual_time_text.get(lang, '⌨️ Ввести время вручную'), callback_data="time_manual")])
        
        time_markup = InlineKeyboardMarkup(inline_keyboard=time_buttons)
        
        # Формируем сообщение с датой и предложением времени
        time_selection_messages = {
            'ru': f"✅ Дата выбрана: {date.strftime('%d.%m.%Y')}\n\nОтлично! На какое время назначить задачу? Выберите из списка или введите вручную (например, 15:30):",
            'en': f"✅ Date selected: {date.strftime('%d.%m.%Y')}\n\nGreat! What time should we schedule the task? Choose from the list or enter manually (e.g., 15:30):",
            'it': f"✅ Data selezionata: {date.strftime('%d.%m.%Y')}\n\nOttimo! A che ora programmare l'attività? Scegli dall'elenco o inserisci manualmente (es: 15:30):"
        }
        
        confirmation_message = time_selection_messages.get(lang, f"✅ Дата выбрана: {date.strftime('%d.%m.%Y')}\n\nОтлично! На какое время назначить задачу? Выберите из списка или введите вручную (например, 15:30):")
        
        # Редактируем текущее сообщение с кнопками времени
        await callback.message.edit_text(
            confirmation_message,
            reply_markup=time_markup
        )
        
        # Переходим к состоянию ожидания времени
        await state.set_state(TaskStates.waiting_for_time)

@dp.callback_query(F.data.startswith("time_"))
async def process_time_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора времени через кнопки"""
    # Получаем язык пользователя из state
    data = await state.get_data()
    lang = data.get('lang', 'ru')
    
    # Извлекаем время из callback_data
    time_value = callback.data.replace("time_", "")
    
    if time_value == "manual":
        # Ручной ввод времени - переключаем на текстовый ввод
        manual_time_messages = {
            'ru': '✍️ Введите время в формате ЧЧ:ММ (например, 15:30):',
            'en': '✍️ Enter time in format HH:MM (e.g., 15:30):',
            'it': '✍️ Inserisci l\'ora in formato HH:MM (es: 15:30):'
        }
        
        await callback.message.edit_text(
            manual_time_messages.get(lang, '✍️ Введите время в формате ЧЧ:ММ (например, 15:30):')
        )
        
        # Убедимся, что состояние FSM установлено на ожидание времени
        await state.set_state(TaskStates.waiting_for_time)
    else:
        # Быстрое время - сохраняем и создаем задачу
        await state.update_data(time=time_value)
        
        # Получаем остальные данные для создания задачи
        task_data = await state.get_data()
        note = task_data.get('note', 'Задача')
        date = task_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        # Создаем задачу
        session = AsyncSessionLocal()
        try:
            from database import ReminderRepository
            reminder = await ReminderRepository.create(
                session=session,
                user_id=callback.from_user.id,
                task_text=note,
                reminder_date=date,
                reminder_time=time_value
            )
            
            success_messages = {
                'ru': f'✅ Задача создана!\n📝 {note}\n📅 {date} в {time_value}',
                'en': f'✅ Task created!\n📝 {note}\n📅 {date} at {time_value}',
                'it': f'✅ Compito creato!\n📝 {note}\n📅 {date} alle {time_value}'
            }
            
            await callback.message.edit_text(
                success_messages.get(lang, f'✅ Задача создана!\n📝 {note}\n📅 {date} в {time_value}')
            )
            
            # Очищаем состояние
            await state.clear()
            
        except Exception as e:
            logger.error(f"Error creating task: {e}")
            error_messages = {
                'ru': '❌ Ошибка при создании задачи',
                'en': '❌ Error creating task',
                'it': '❌ Errore nella creazione del compito'
            }
            await callback.message.edit_text(error_messages.get(lang, '❌ Ошибка при создании задачи'))
        finally:
            await session.close()

@dp.message(TaskStates.waiting_for_note)
async def get_note(message: types.Message, state: FSMContext, **data):
    """Обрабатывает текст заметки через NLP, создаёт задачи если данные полные"""
    session = data.get("session")
    if not session:
        logger.error("=== get_note: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    text = message.text
    
    # Получаем язык пользователя
    lang = await UserRepository.get_lang(session, user_id)
    
    # Получаем текст кнопки отмены для текущего языка
    cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
    
    # Если пользователь нажал "Отмена"
    if message.text == cancel_text:
        await state.clear()  # Сбрасываем состояние FSM
        # Отправляем главное меню
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
                 KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
            ], 
            resize_keyboard=True
        )
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('welcome_back', '🏠 Main menu. What\'s next?'),
            reply_markup=kb
        )
        return
    
    print(f">>> get_note: processing text through NLP: {text[:50]}...")
    
    # Проверяем, что пользователь ввел только время (например, "18:55")
    import re
    time_pattern = r'^([01]\d|2[0-3]):([0-5]\d)$'
    if re.match(time_pattern, text.strip()):
        # Пользователь ввел только время, но не указал задачу
        time_only_messages = {
            'ru': f"⏰ Я понял время {text.strip()}, но не понял, что нужно сделать. Напишите, например: Купить кофе {text.strip()}",
            'en': f"⏰ I understood the time {text.strip()}, but didn't understand what needs to be done. For example, write: Buy coffee {text.strip()}",
            'it': f"⏰ Ho capito l'ora {text.strip()}, ma non ho capito cosa fare. Per esempio, scrivi: Comprare caffè {text.strip()}"
        }
        
        await message.answer(time_only_messages.get(lang, time_only_messages['ru']))
        return
    
    # Вызываем NLP для парсинга текста
    parsed = await parse_task(text)
    
    print(f">>> get_note: NLP result: {parsed}")
    print(f">>> get_note: success={parsed.get('success')}, tasks_count={len(parsed.get('tasks', []))}")
    
    # Проверяем результат NLP
    success = parsed.get('success', False)
    tasks = parsed.get('tasks', [])
    
    # Если NLP вернул ошибку ИЛИ нет задач - идем в FSM
    if not success or not tasks:
        print(f">>> get_note: ENTERING FSM (success={success}, has_tasks={bool(tasks)})")
        # Важно: используем original_text если есть (при Rate Limit), иначе message.text
        note_text = parsed.get('original_text', text)
        
        # --- ЛОКАЛЬНЫЙ ПАРСИНГ RECURRENCE ЧЕРЕЗ REGEX ---
        recurrence = parse_recurrence_from_text(note_text)
        if recurrence:
            print(f">>> get_note: LOCAL REGEX found recurrence='{recurrence}' in text")
        
        # Удаляем ключевые слова recurrence из текста задачи
        clean_note = clean_recurrence_keywords(note_text, recurrence)
        
        await state.update_data(note=clean_note, recurrence=recurrence)
        
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text=MESSAGES[lang]['today']), KeyboardButton(text=MESSAGES[lang]['tomorrow'])],
            [KeyboardButton(text=MESSAGES[lang]['after'])],
            [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]
        ], resize_keyboard=True)
        
        await state.set_state(TaskStates.waiting_for_date)
        await message.answer(MESSAGES[lang]['ask_date'], reply_markup=kb)
        return
    
    print(f">>> get_note: NLP SUCCESS, processing {len(tasks)} tasks")
    
    # Получаем список задач от NLP
    tasks = parsed['tasks']
    
    # Проверяем, все ли задачи имеют полные данные (наличие date И time)
    complete_tasks = [t for t in tasks if t.get('date') and t.get('time')]
    incomplete_tasks = [t for t in tasks if not (t.get('date') and t.get('time'))]
    
    print(f">>> get_note: {len(complete_tasks)} complete, {len(incomplete_tasks)} incomplete tasks")
    
    # Детальное логирование первой задачи
    if tasks:
        first_task = tasks[0]
        print(f">>> get_note: first task details: task='{first_task.get('task')}', date={first_task.get('date')}, time={first_task.get('time')}, city={first_task.get('city')}, is_complete_flag={first_task.get('is_complete_data')}")
    
    # Если есть полные задачи - создаем их
    created_tasks = []
    if complete_tasks:
        print(f">>> get_note: creating {len(complete_tasks)} complete tasks...")
        for task_data in complete_tasks:
            try:
                task_text = task_data['task']
                date_str = task_data['date']
                time_str = task_data['time']
                city = task_data.get('city')
                
                # Если города нет - берем дефолт
                if not city:
                    last_reminder = await ReminderRepository.get_last_reminder(session, user_id)
                    city = last_reminder.city if last_reminder and last_reminder.city else "Тбилиси"
                
                # Парсим локальное время
                local_time = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                
                # Конвертируем в UTC
                tz_offset_hours = 3
                remind_at_utc = local_time - timedelta(hours=tz_offset_hours)
                
                # Если время уже прошло - переносим на завтра
                utc_now = datetime.now(timezone.utc)
                if remind_at_utc <= utc_now:
                    remind_at_utc = remind_at_utc + timedelta(days=1)
                    local_time = local_time + timedelta(days=1)
                
                # Создаем напоминание
                reminder = await ReminderRepository.create(
                    session=session,
                    user_id=user_id,
                    task_text=task_text,
                    remind_at=remind_at_utc,
                    city=city
                )
                
                # Добавляем в планировщик
                scheduler.add_job(
                    send_scheduled_reminder,
                    'date',
                    run_date=remind_at_utc,
                    args=[user_id, task_text, city, lang, reminder.id],
                    id=f"reminder_{reminder.id}",
                    misfire_grace_time=7200  # 2 часа для обработки пропущенных задач
                )
                
                created_tasks.append({
                    'id': reminder.id,
                    'text': task_text,
                    'date': local_time.strftime("%d.%m.%Y"),
                    'time': local_time.strftime("%H:%M"),
                    'city': city
                })
                
                # Логируем
                bot_logger.log_user_action(user_id, "REMINDER_CREATED", {
                    "reminder_id": reminder.id,
                    "task_text": task_text,
                    "remind_at": remind_at_utc.isoformat()
                })
                
            except Exception as e:
                logger.error(f"Error creating reminder from NLP: {e}")
                print(f">>> get_note: error creating task: {e}")
    
    # Формируем ответ в зависимости от результата
    if len(created_tasks) == 1:
        # Одна задача создана
        task = created_tasks[0]
        await message.answer(
            f"✅ Понял, всё записал!",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text=MESSAGES[lang]['btn_task']), KeyboardButton(text=MESSAGES[lang]['btn_my_tasks'])],
                    [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
                ],
                resize_keyboard=True
            )
        )
        await state.clear()
        return  # Важно: прерываем выполнение!
        
    elif len(created_tasks) > 1:
        # Несколько задач созданы
        tasks_list = "\n".join([
            f"{i+1}. {t['text']} ({t['time']}, {t['date']})"
            for i, t in enumerate(created_tasks)
        ])
        await message.answer(
            f"✅ Понял, всё записал!\n{tasks_list}",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text=MESSAGES[lang]['btn_task']), KeyboardButton(text=MESSAGES[lang]['btn_my_tasks'])],
                    [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
                ],
                resize_keyboard=True
            )
        )
        await state.clear()
        return  # Важно: прерываем выполнение!
        
    elif incomplete_tasks:
            # Есть неполные задачи - берем первую и продолжаем FSM
            task_data = incomplete_tasks[0]
            lang = data.get('lang', 'ru')
            
            # Сохраняем то, что вытащили
            await state.update_data(
                note=task_data.get('task', text),
                city=task_data.get('city'),
                recurrence=task_data.get('recurrence')
            )
            
            # Вызываем календарь
            labels = CALENDAR_LABLES.get(lang, CALENDAR_LABLES['en'])
            calendar = SimpleCalendar()
            calendar.days_names = labels['days_names']
            calendar.months_names = labels['months_names']
    
            await message.answer(
                MESSAGES[lang]['choose_date'], 
                reply_markup=await calendar.start_calendar()
            )
            await state.set_state(TaskStates.waiting_for_date)

@dp.message(TaskStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext, **data):
    """Обрабатывает ввод даты - кнопки Сегодня/Завтра или текст"""
    session = data.get("session")
    if not session:
        logger.error("=== process_date: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    lang = await UserRepository.get_lang(session, user_id)
    
    # Получаем текст кнопки отмены для текущего языка
    cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
    
    # Если пользователь нажал "Отмена"
    if message.text == cancel_text:
        await state.clear()  # Сбрасываем состояние FSM
        # Отправляем главное меню
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
                 KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
            ], 
            resize_keyboard=True
        )
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('welcome_back', '🏠 Main menu. What\'s next?'),
            reply_markup=kb
        )
        return
    
    text = message.text.strip().lower()
    
    # Получаем текущую дату
    today = datetime.now().date()
    
    # Обрабатываем кнопки
    if text == MESSAGES[lang]['today'].lower():
        date_obj = today
        await state.update_data(date=date_obj.isoformat())
        await message.answer(MESSAGES[lang]['ask_time'], reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]],
            resize_keyboard=True
        ))
        await state.set_state(TaskStates.waiting_for_time)
        
    elif text == MESSAGES[lang]['tomorrow'].lower():
        date_obj = today + timedelta(days=1)
        await state.update_data(date=date_obj.isoformat())
        await message.answer(MESSAGES[lang]['ask_time'], reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]],
            resize_keyboard=True
        ))
        await state.set_state(TaskStates.waiting_for_time)
        
    elif text == MESSAGES[lang]['after'].lower():
        # Показываем календарь для выбора даты
        labels = CALENDAR_LABLES.get(lang, CALENDAR_LABLES['en'])
        calendar = SimpleCalendar()
        calendar.days_names = labels['days_names']
        calendar.months_names = labels['months_names']
        
        await message.answer(
            MESSAGES[lang]['choose_date'], 
            reply_markup=await calendar.start_calendar()
        )
        # Остаемся в том же состоянии waiting_for_date для календаря
        
    else:
        # Попробуем распарсить дату в формате ДД.ММ или ДД.ММ.ГГГГ
        try:
            if '.' in text:
                parts = text.split('.')
                if len(parts) == 2:
                    # ДД.ММ
                    day, month = map(int, parts)
                    year = today.year
                elif len(parts) == 3:
                    # ДД.ММ.ГГГГ
                    day, month, year = map(int, parts)
                else:
                    raise ValueError("Неверный формат даты")
                
                date_obj = datetime(year, month, day).date()
                
                # Проверяем, что дата не в прошлом
                if date_obj < today:
                    await message.answer(MESSAGES.get(lang, MESSAGES['ru'])['error_date'])
                    return
                
                await state.update_data(date=date_obj.isoformat())
                await message.answer(MESSAGES[lang]['ask_time'], reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel'))]],
            resize_keyboard=True
        ))
                await state.set_state(TaskStates.waiting_for_time)
                
            else:
                await message.answer(
                    MESSAGES.get(lang, MESSAGES['ru'])['error_date']
                )
        except (ValueError, TypeError):
            await message.answer(
                MESSAGES.get(lang, MESSAGES['ru'])['error_date']
            )

@dp.message(TaskStates.waiting_for_time)
async def process_time(message: types.Message, state: FSMContext, **data):
    """Обрабатывает ввод времени"""
    session = data.get("session")
    if not session:
        logger.error("=== process_time: session НЕ НАЙДЕНА!")
        await message.answer(MESSAGES.get(lang, MESSAGES['ru'])['db_error'])
        return
    
    user_id = message.from_user.id
    
    # Get user and language directly from database
    user = await UserRepository.get_by_id(session, user_id)
    lang = user.lang if user else 'en'
    
    # Получаем текст кнопки отмены для текущего языка
    cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
    
    # Если пользователь нажал "Отмена"
    if message.text == cancel_text:
        await state.clear()  # Сбрасываем состояние FSM
        # Отправляем главное меню
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
                 KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
            ], 
            resize_keyboard=True
        )
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('welcome_back', '🏠 Main menu. What\'s next?'),
            reply_markup=kb
        )
        return
    
    text = message.text.strip()
    
    # Add detailed logging for time validation
    import re
    from datetime import datetime
    import pytz
    
    logging.info(f"DEBUG TIME: user_input='{message.text}', server_now='{datetime.now()}'")
    
    # Получаем часовой пояс пользователя динамически
    user = await UserRepository.get_by_id(session, message.from_user.id)
    user_timezone = user.timezone if user and user.timezone else 'UTC'
    logging.info(f"DEBUG TASK: Using timezone from DB: '{user_timezone}'")
            
    if user_timezone == 'UTC':
        # Отправляем предупреждение о не настроенном часовом поясе
        timezone_warning_messages = {
            'ru': "⚠️ Ваш часовой пояс не настроен, использую UTC. Вы можете изменить это в настройках.",
            'en': "⚠️ Your timezone is not set, using UTC. You can change this in settings.",
            'it': "⚠️ Il tuo fuso orario non è impostato, uso UTC. Puoi cambiarlo nelle impostazioni."
        }
        await message.answer(timezone_warning_messages.get(lang, "⚠️ Ваш часовой пояс не настроен, использую UTC. Вы можете изменить это в настройках."))
    
    try:
        user_tz = pytz.timezone(user_timezone)
        user_now = datetime.now(user_tz)
        logging.info(f"DEBUG TIME: user_timezone='{user_timezone}', user_now='{user_now}'")
    except Exception as e:
        logging.error(f"DEBUG TIME: Error getting timezone '{user_timezone}': {e}")
        # Fallback to UTC if timezone is invalid
        user_tz = pytz.UTC
        user_now = datetime.now(pytz.UTC)
        logging.info(f"DEBUG TIME: Fallback to UTC, user_now='{user_now}'")
    
    # Парсим время в формате ЧЧ:ММ с улучшенным regex
    try:
        logging.info(f"DEBUG TIME: Starting time parsing for '{text}'")
        
        # Используем regex для валидации формата HH:MM
        time_pattern = r'^([01]\d|2[0-3]):([0-5]\d)$'
        match = re.match(time_pattern, text.strip())
        
        if match:
            # Формат HH:MM - извлекаем часы и минуты
            hours = int(match.group(1))
            minutes = int(match.group(2))
            logging.info(f"DEBUG TIME: Regex matched - hours={hours}, minutes={minutes}")
        else:
            # Проверяем формат H:MM (однозначные часы)
            time_pattern_hmm = r'^(\d):([0-5]\d)$'
            match_hmm = re.match(time_pattern_hmm, text.strip())
            
            if match_hmm:
                hours = int(match_hmm.group(1))
                minutes = int(match_hmm.group(2))
                logging.info(f"DEBUG TIME: H:MM format matched - hours={hours}, minutes={minutes}")
            else:
                # Пробуем распарсить как ЧЧММ (например, 1430)
                if len(text.strip()) == 4 and text.strip().isdigit():
                    hours = int(text.strip()[:2])
                    minutes = int(text.strip()[2:])
                    logging.info(f"DEBUG TIME: HHMM format matched - hours={hours}, minutes={minutes}")
                else:
                    logging.error(f"DEBUG TIME: No time format matched for '{text}'")
                    raise ValueError(f"Неверный формат времени: '{text}'. Ожидался формат ЧЧ:ММ (например, 17:00)")
        
        # Дополнительная проверка валидности времени
        if not (0 <= hours <= 23 and 0 <= minutes <= 59):
            logging.error(f"DEBUG TIME: Invalid time values - hours={hours}, minutes={minutes}")
            raise ValueError(f"Неверное время: {hours:02d}:{minutes:02d}")
        
        # Формируем время
        time_str = f"{hours:02d}:{minutes:02d}"
        logging.info(f"DEBUG TIME: Time parsed successfully - time_str='{time_str}'")
        
        # Сохраняем время в состояние
        await state.update_data(time=time_str)
        
        # Получаем все данные из состояния
        state_data = await state.get_data()
        note = state_data.get('note', '')
        date = state_data.get('date', '')
        city = state_data.get('city', '')
        recurrence = state_data.get('recurrence', '')
        
        # Создаем задачу
        try:
            data = await state.get_data()
            lang = data.get('lang', 'ru')
            
            # Check task limit before creating
            active_tasks_count = await ReminderRepository.get_active_count(session, message.from_user.id)
            if active_tasks_count >= MAX_TASKS:
                limit_msg = MESSAGES.get(lang, MESSAGES['ru']).get('task_limit_exceeded', '⚠️ Too many tasks! Delete old ones before adding new ones. Maximum: {max} tasks.').format(max=MAX_TASKS)
                await message.answer(limit_msg)
                return
            
            # Вместо repo = ReminderRepository(db_session)
            # Используем метод класса напрямую, передавая сессию внутрь
            
            # Получаем город пользователя из базы данных
            user_city = await UserRepository.get_city(session, message.from_user.id)
            
            # Warn user if no city is set
            if not user_city or user_city == 'UTC':
                await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('no_city_warning', '⚠️ You haven\'t set a city! Using UTC by default.'))
            
            # Конвертируем дату и время в datetime
            from datetime import datetime
            data = await state.get_data()
            logging.info(f"Full state data: {data}")
            
            date_str = data.get('date', '').strip()
            time_str = time_str.strip()
            
            logging.info(f"DEBUG TASK: date_str='{date_str}', time_str='{time_str}'")
            
            # Проверяем, что дата не пустая
            if not date_str:
                logging.error(f"DEBUG TASK: Empty date_str from state")
                # Возвращаем пользователя на шаг выбора даты
                date_lost_messages = {
                    'ru': "Извините, дата потерялась. Пожалуйста, выберите её снова в календаре",
                    'en': "Sorry, the date was lost. Please select it again in the calendar",
                    'it': "Scusa, la data è andata persa. Per favore, selezionala di nuovo nel calendario"
                }
                await message.answer(date_lost_messages.get(lang, "Извините, дата потерялась. Пожалуйста, выберите её снова в календаре"))
                
                # Показываем календарь снова
                labels = CALENDAR_LABLES.get(lang, CALENDAR_LABLES['en'])
                calendar = SimpleCalendar()
                calendar.days_names = labels['days_names']
                calendar.months_names = labels['months_names']
                
                await message.answer(
                    MESSAGES[lang]['choose_date'], 
                    reply_markup=await calendar.start_calendar()
                )
                return
            
            # Используем правильный формат (дата сохраняется как %d.%m.%Y из календаря)
            try:
                remind_at_local = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
                logging.info(f"DEBUG TASK: Successfully parsed datetime: {remind_at_local}")
            except ValueError as e:
                logging.error(f"DEBUG TASK: Date parsing error: {e}")
                await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('error_general', f'❌ Error parsing date/time: {e}'))
                return
            
            # Получаем timezone пользователя динамически
            user = await UserRepository.get_by_id(session, message.from_user.id)
            user_timezone = user.timezone if user and user.timezone else 'UTC'
            logging.info(f"DEBUG TASK: Using timezone from DB: '{user_timezone}'")
            
            try:
                user_tz = pytz.timezone(user_timezone)
                # Правильная конвертация: сначала локализуем naive datetime, потом конвертируем в UTC
                localized_dt = user_tz.localize(remind_at_local)
                remind_at_utc = localized_dt.astimezone(pytz.UTC)
                logging.info(f"DEBUG TASK: Localized {remind_at_local} to {localized_dt} ({user_timezone})")
                logging.info(f"DEBUG TASK: Converted to UTC: {remind_at_utc}")
            except Exception as e:
                logging.error(f"DEBUG TASK: Error converting timezone '{user_timezone}': {e}")
                # Если ошибка, используем UTC
                remind_at_utc = remind_at_local.replace(tzinfo=pytz.UTC)
                logging.info(f"DEBUG TASK: Fallback to UTC: {remind_at_utc}")
            
            # Получаем город для информации (не для timezone)
            user_city = await UserRepository.get_city(session, message.from_user.id)
            
            # Warn user if timezone is not set
            if user_timezone == 'UTC':
                timezone_warning_messages = {
                    'ru': "⚠️ Ваш часовой пояс не настроен, использую UTC. Вы можете изменить это в настройках.",
                    'en': "⚠️ Your timezone is not set, using UTC. You can change this in settings.",
                    'it': "⚠️ Il tuo fuso orario non è impostato, uso UTC. Puoi cambiarlo nelle impostazioni."
                }
                await message.answer(timezone_warning_messages.get(lang, "⚠️ Ваш часовой пояс не настроен, использую UTC. Вы можете изменить это в настройках."))
            
            # Если время уже прошло - переносим на завтра (с небольшой буферной зоной)
            utc_now = datetime.now(pytz.UTC)
            # Add 2-minute buffer to allow creating tasks for very near future
            if remind_at_utc <= utc_now - timedelta(minutes=2):
                remind_at_utc = remind_at_utc + timedelta(days=1)
                remind_at_local = remind_at_local + timedelta(days=1)
                logging.info(f"Time was in the past, moved to next day: {remind_at_utc}")
            else:
                logging.info(f"Time is valid for today: {remind_at_utc}")
            
            new_reminder = await ReminderRepository.create(
                session=session,  # Передаем сессию прямо в метод
                user_id=message.from_user.id,
                task_text=data['note'],
                remind_at=remind_at_utc,
                city=user_city,
                recurrence=data.get('recurrence')
            )
            
            # Добавляем в планировщик
            logging.info(f"DEBUG SCHEDULER: Final run_date for scheduler: {remind_at_utc} UTC")
            logging.info(f"DEBUG SCHEDULER: Job ID: reminder_{new_reminder.id}")
            logging.info(f"DEBUG SCHEDULER: Task: '{data['note']}' for user {message.from_user.id}")
            scheduler.add_job(
                send_scheduled_reminder,
                'date',
                run_date=remind_at_utc,
                args=[message.from_user.id, data['note'], user_city, lang, new_reminder.id],
                id=f"reminder_{new_reminder.id}",
                misfire_grace_time=7200  # 2 часа для обработки пропущенных задач
            )
            logging.info(f"DEBUG SCHEDULER: Job successfully added to scheduler")
            
            # Берем сообщение с учетом языка (use the lang we got from database)
            lang_dict = MESSAGES.get(lang, MESSAGES['ru'])
            task_created_msg = lang_dict.get('task_created', '✅ Задача создана!')
            
            # Handle both string and dictionary formats for task_created
            if isinstance(task_created_msg, dict):
                msg_tpl = task_created_msg.get(lang, '✅ Задача создана!')
            else:
                msg_tpl = task_created_msg
            
            await message.answer(msg_tpl.format(
                task=data['note'],
                date=remind_at_local.strftime('%d.%m.%Y'),
                time=time_str
            ), reply_markup=ReplyKeyboardRemove())
            await state.clear() # ОБЯЗАТЕЛЬНО очищаем стейт после успеха

        except Exception as e:
            logging.error(f"Error creating reminder: {e}", exc_info=True)
            await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('error_time', '❌ Invalid time format. Enter in HH:MM, e.g., 14:30.'))
            # Стейт НЕ очищаем, чтобы пользователь мог попробовать ввести время снова
            
    except (ValueError, TypeError):
        await message.answer(MESSAGES.get(lang, MESSAGES['ru']).get('error_time', '❌ Invalid time format. Enter in HH:MM, e.g., 14:30.'))

@dp.message(TaskStates.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext, **data):
    """Обрабатывает ввод города"""
    session = data.get("session")
    if not session:
        logger.error("=== process_city: session НЕ НАЙДЕНА!")
        await message.answer("Ошибка: сессия БД не найдена")
        return
    
    user_id = message.from_user.id
    
    # Get user and language from database
    user = await UserRepository.get_by_id(session, user_id)
    lang = user.lang if user else 'ru'
    
    city_name = message.text.strip()
    
    # Получаем текст кнопки отмены для текущего языка
    cancel_text = MESSAGES.get(lang, MESSAGES['ru']).get('btn_cancel', '❌ Cancel')
    
    # Проверяем, что это не команда отмены
    if city_name == cancel_text:
        await state.clear()
        # Отправляем главное меню
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
                 KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
            ], 
            resize_keyboard=True
        )
        await message.answer(
            MESSAGES.get(lang, MESSAGES['ru']).get('welcome_back', '🏠 Main menu. What\'s next?'),
            reply_markup=kb
        )
        return
    
    try:
        # Пытаемся получить timezone для города
        # Простая маппинг для популярных городов
        city_timezone_map = {
            # Russian cities
            'москва': 'Europe/Moscow',
            'moscow': 'Europe/Moscow',
            'санкт-петербург': 'Europe/Moscow',
            'saint petersburg': 'Europe/Moscow',
            'киев': 'Europe/Kyiv',
            'kyiv': 'Europe/Kyiv',
            'минск': 'Europe/Minsk',
            'minsk': 'Europe/Minsk',
            'алматы': 'Asia/Almaty',
            'almaty': 'Asia/Almaty',
            
            # Georgian cities
            'тбилиси': 'Asia/Tbilisi',
            'tbilisi': 'Asia/Tbilisi',
            'батуми': 'Asia/Tbilisi',
            'batumi': 'Asia/Tbilisi',
            
            # Turkish cities
            'анталья': 'Europe/Istanbul',
            'antalya': 'Europe/Istanbul',
            'стамбул': 'Europe/Istanbul',
            'istanbul': 'Europe/Istanbul',
            'измир': 'Europe/Istanbul',
            'izmir': 'Europe/Istanbul',
            'анкара': 'Europe/Istanbul',
            'ankara': 'Europe/Istanbul',
            
            # European cities
            'нью-йорк': 'America/New_York',
            'new york': 'America/New_York',
            'лондон': 'Europe/London',
            'london': 'Europe/London',
            'париж': 'Europe/Paris',
            'paris': 'Europe/Paris',
            'берлин': 'Europe/Berlin',
            'berlin': 'Europe/Berlin',
            'рим': 'Europe/Rome',
            'rome': 'Europe/Rome',
            'мадрид': 'Europe/Madrid',
            'madrid': 'Europe/Madrid',
            
            # Asian cities
            'дубай': 'Asia/Dubai',
            'dubai': 'Asia/Dubai',
            'токио': 'Asia/Tokyo',
            'tokyo': 'Asia/Tokyo',
            'пекин': 'Asia/Shanghai',
            'beijing': 'Asia/Shanghai',
            'сидней': 'Australia/Sydney',
            'sydney': 'Australia/Sydney'
        }
        
        # Ищем timezone
        timezone_name = city_timezone_map.get(city_name.lower())
        
        if not timezone_name:
            # Пробуем определить по первым буквам
            for city_key, tz in city_timezone_map.items():
                if city_name.lower().startswith(city_key[:3]):
                    timezone_name = tz
                    break
        
        if not timezone_name:
            # Если не нашли, используем UTC
            timezone_name = 'UTC'
            msg = MESSAGES.get(lang, MESSAGES['ru']).get('city_not_found', '❌ City {city} not found. Try entering in English.').format(city=city_name)
            await message.answer(msg)
        else:
            # Проверяем, что timezone существует
            try:
                tz = ZoneInfo(timezone_name)
                msg = MESSAGES.get(lang, MESSAGES['ru']).get('city_set', '✅ City set: {city}. Timezone: {timezone}').format(city=city_name, timezone=timezone_name)
                await message.answer(msg)
            except Exception:
                timezone_name = 'UTC'
                msg = MESSAGES.get(lang, MESSAGES['ru']).get('city_timezone_error', '❌ Could not determine timezone for city {city}.').format(city=city_name)
                await message.answer(msg)
        
        # Сохраняем город в базу данных
        await UserRepository.set_city(session, user_id, city_name)
        
        # Показываем главное меню после успешной установки города
        kb = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_task', '📅 Tasks')), 
                 KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_my_tasks', '🗂 My Tasks'))],
                [KeyboardButton(text=MESSAGES.get(lang, MESSAGES['ru']).get('btn_horoscope', '🔮 Horoscope'))]
            ], 
            resize_keyboard=True
        )
        
        welcome_msg = MESSAGES.get(lang, MESSAGES['ru']).get('main_menu', '🏠 Main menu. What\'s next?')
        await message.answer(welcome_msg, reply_markup=kb)
        
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error setting city: {e}", exc_info=True)
        await message.answer("❌ An unexpected error occurred while setting the city. Please try again.")
    
# --- ЗАПУСК БОТА ---
async def main():
    # Инициализация БД
    await init_db()
    
    # Установка команд меню бота
    await set_bot_commands()
    
    # Запуск планировщика
    scheduler.start()
    
    # Запуск polling
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")