import os
import asyncio
import logging
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiohttp import web

# --- НАСТРОЙКИ ---
API_TOKEN = os.environ.get("BOT_TOKEN")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()

# --- СОСТОЯНИЯ (FSM) ---
class TaskStates(StatesGroup):
    waiting_for_note = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_city = State()

# --- СЛОВАРЬ (RU, EN, IT) ---
MESSAGES = {
    'ru': {
        'start': "Выберите язык:",
        'main_menu': "Вы выбрали русский язык. Что делаем?",
        'btn_task': "📅 Задачи",
        'ask_note': "Введите текст вашей заметки:",
        'ask_date': "Когда напомнить?",
        'ask_time': "Введите время (например, 14:30):",
        'ask_city': "В каком городе проверить погоду для уведомления?",
        'today': "Сегодня", 'tomorrow': "Завтра", 'after': "Послезавтра",
        'confirm': "✅ Напоминание создано! Пришлю его вместе с погодой и качеством воздуха.",
        'reminder_text': "🔔 НАПОМИНАНИЕ: {note}\n\n📍 Город: {city}\n🌤 Погода: {temp}°C, {desc}\n💨 Качество воздуха: {aqi}"
    },
    'en': {
        'start': "Choose language:",
        'main_menu': "English selected. What's next?",
        'btn_task': "📅 Tasks",
        'ask_note': "Enter your note text:",
        'ask_date': "When to remind?",
        'ask_time': "Enter time (e.g., 14:30):",
        'ask_city': "In which city should I check the weather?",
        'today': "Today", 'tomorrow': "Tomorrow", 'after': "Day after tomorrow",
        'confirm': "✅ Reminder set! I'll send it with weather and air quality report.",
        'reminder_text': "🔔 REMINDER: {note}\n\n📍 City: {city}\n🌤 Weather: {temp}°C, {desc}\n💨 Air Quality: {aqi}"
    },
    'it': {
        'start': "Scegli la lingua:",
        'main_menu': "Lingua italiana selezionata. Cosa facciamo?",
        'btn_task': "📅 Compiti",
        'ask_note': "Inserisci il testo della tua nota:",
        'ask_date': "Quando ti ricordo?",
        'ask_time': "Inserisci l'ora (es. 14:30):",
        'ask_city': "In quale città controllo il meteo?",
        'today': "Oggi", 'tomorrow': "Domani", 'after': "Dopodomani",
        'confirm': "✅ Promemoria impostato! Lo invierò con il meteo e la qualità dell'aria.",
        'reminder_text': "🔔 PROMEMORIA: {note}\n\n📍 Città: {city}\n🌤 Meteo: {temp}°C, {desc}\n💨 Qualità dell'aria: {aqi}"
    }
}

# --- ПОГОДА И КАЧЕСТВО ВОЗДУХА ---
async def fetch_weather_data(city, lang):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang={lang}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200: return None
            data = await resp.json()
            lat, lon = data['coord']['lat'], data['coord']['lon']
            tz_offset = data.get('timezone', 0)
            
            # Дополнительный запрос на качество воздуха
            air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}"
            async with session.get(air_url) as a_resp:
                air_data = await a_resp.json()
                aqi_val = air_data['list'][0]['main']['aqi']
                aqi_map = {1: "Excellent", 2: "Good", 3: "Fair", 4: "Poor", 5: "Very Poor"}
            
            return {
                'temp': data['main']['temp'],
                'desc': data['weather'][0]['description'],
                'aqi': aqi_map.get(aqi_val, "N/A"),
                'tz_offset': tz_offset
            }

async def send_scheduled_reminder(chat_id, note, city, lang):
    w = await fetch_weather_data(city, lang)
    if w:
        text = MESSAGES[lang]['reminder_text'].format(
            note=note, city=city, temp=w['temp'], desc=w['desc'], aqi=w['aqi']
        )
    else:
        text = f"🔔 {note}\n(Weather data for {city} unavailable)"
    await bot.send_message(chat_id, text)

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
async def select_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[-1]
    await state.update_data(lang=lang)
    
    # Главное меню с кнопкой Задачи
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MESSAGES[lang]['btn_task'])]], 
        resize_keyboard=True
    )
    await callback.message.answer(MESSAGES[lang]['main_menu'], reply_markup=kb)
    await callback.answer()

@dp.message(F.text.in_({"📅 Задачи", "📅 Tasks", "📅 Compiti"}))
async def start_task_creation(message: types.Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get('lang', 'ru')
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
async def get_city_and_finish(message: types.Message, state: FSMContext):
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
        error_texts = {
            'ru': "Не удалось найти такой город. Проверьте название и попробуйте снова.",
            'en': "Could not find this city. Please check the name and try again.",
            'it': "Impossibile trovare questa città. Controlla il nome e riprova."
        }
        await message.answer(error_texts.get(lang, error_texts['en']))
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
        invalid_date_texts = {
            'ru': "Некорректная дата. Пожалуйста, выберите одну из предложенных кнопок.",
            'en': "Invalid date. Please choose one of the suggested options.",
            'it': "Data non valida. Scegli una delle opzioni proposte."
        }
        await message.answer(invalid_date_texts.get(lang, invalid_date_texts['en']))
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
        invalid_time_texts = {
            'ru': "Некорректный формат времени. Введите в формате ЧЧ:ММ, например, 14:30.",
            'en': "Invalid time format. Use HH:MM, e.g., 14:30.",
            'it': "Formato orario non valido. Usa HH:MM, ad es., 14:30."
        }
        await message.answer(invalid_time_texts.get(lang, invalid_time_texts['en']))
        return

    # Собираем локальное datetime в выбранном городе
    local_target = datetime(year=target_date.year, month=target_date.month, day=target_date.day, hour=hour, minute=minute)

    # Если локальное время уже прошло — переносим на следующий день
    if local_target <= local_now:
        local_target = local_target + timedelta(days=1)

    # Конверт��руем локальное время в UTC для планировщика: local - tz_offset
    remind_at_utc = local_target - timedelta(seconds=tz_offset)

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
    # Start the health-check web server before entering the polling loop
    asyncio.create_task(start_web_server())
    scheduler.start()

    # Survival loop for polling to auto-recover from transient failures
    while True:
        try:
            await dp.start_polling(bot)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            await asyncio.sleep(5)
            continue
        # If polling exits cleanly, break to avoid tight loop
        break

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped")