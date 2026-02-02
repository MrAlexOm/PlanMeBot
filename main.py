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

# --- ТЕКСТЫ ---
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
        'confirm': "✅ Напоминание создано! Пришлю его вместе с погодой.",
        'reminder_text': "🔔 НАПОМИНАНИЕ: {note}\n\n🌤 Погода в {city}: {temp}°C, {desc}\n💨 Воздух: {aqi}"
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
        'confirm': "✅ Reminder set! I'll send it with the weather report.",
        'reminder_text': "🔔 REMINDER: {note}\n\n🌤 Weather in {city}: {temp}°C, {desc}\n💨 Air: {aqi}"
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
        'confirm': "✅ Promemoria impostato! Lo invierò con il meteo.",
        'reminder_text': "🔔 PROMEMORIA: {note}\n\n🌤 Meteo a {city}: {temp}°C, {desc}\n💨 Aria: {aqi}"
    }
}

# --- ПОГОДА ---
async def fetch_weather_data(city, lang):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang={lang}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200: return None
            data = await resp.json()
            lat, lon = data['coord']['lat'], data['coord']['lon']
            
            air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}"
            async with session.get(air_url) as a_resp:
                air_data = await a_resp.json()
                aqi_val = air_data['list'][0]['main']['aqi']
                aqi_map = {1: "Excellent", 2: "Good", 3: "Fair", 4: "Poor", 5: "Very Poor"}
            
            return {
                'temp': data['main']['temp'],
                'desc': data['weather'][0]['description'],
                'aqi': aqi_map.get(aqi_val, "N/A")
            }

async def send_scheduled_reminder(chat_id, note, city, lang):
    w = await fetch_weather_data(city, lang)
    if w:
        text = MESSAGES[lang]['reminder_text'].format(note=note, city=city, temp=w['temp'], desc=w['desc'], aqi=w['aqi'])
    else:
        text = f"🔔 {note} (Weather data unavailable)"
    await bot.send_message(chat_id, text)

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton(text="English 🇺🇸", callback_data="lang_en")],
        [InlineKeyboardButton(text="Italiano 🇮🇹", callback_data="lang_it")]
    ])
    await message.answer("Choose language / Выберите язык:", reply_markup=kb)

@dp.callback_query(F.data.startswith("set_lang_") or F.data.startswith("lang_"))
async def select_lang(callback: types.CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[-1]
    await state.update_data(lang=lang)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=MESSAGES[lang]['btn_task'])]], resize_keyboard=True)
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
    
    # Расчет времени (упрощенно: напоминание через 1 минуту для теста)
    # Здесь можно добавить парсинг даты и времени из data['date_text'] и data['time_text']
    remind_at = datetime.now() + timedelta(minutes=1) 
    
    scheduler.add_job(
        send_scheduled_reminder, 
        'date', 
        run_date=remind_at, 
        args=[message.chat.id, data['note'], city, lang]
    )
    
    await message.answer(MESSAGES[lang]['confirm'])
    await state.clear()

# --- SERVER ---
async def handle(request): return web.Response(text="PlanMe Live")
async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 10000))).start()

async def main():
    asyncio.create_task(start_web_server())
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())