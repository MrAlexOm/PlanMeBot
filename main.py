import os
import asyncio
import logging
import aiosqlite
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web

# --- НАСТРОЙКИ ---
API_TOKEN = os.environ.get("BOT_TOKEN")
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- СЛОВАРЬ (RU, EN, IT) ---
MESSAGES = {
    'ru': {
        'start': "Привет! Выберите действие:",
        'weather': "🌤 Погода и Воздух",
        'tasks': "📅 Задачи",
        'lang': "🌐 Сменить язык",
        'city_prompt': "Напишите название города:",
        'air': "Качество воздуха"
    },
    'en': {
        'start': "Hello! Choose an action:",
        'weather': "🌤 Weather & Air",
        'tasks': "📅 Tasks",
        'lang': "🌐 Change Language",
        'city_prompt': "Type the city name:",
        'air': "Air Quality"
    },
    'it': {
        'start': "Ciao! Scegli un'azione:",
        'weather': "🌤 Meteo e Aria",
        'tasks': "📅 Compiti",
        'lang': "🌐 Cambia lingua",
        'city_prompt': "Scrivi il nome della città:",
        'air': "Qualità dell'aria"
    }
}

# --- RENDER HEALTH CHECK ---
async def handle(request):
    return web.Response(text="Bot is Alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()

# --- ПОГОДА И ВОЗДУХ ---
async def get_weather(city, lang='ru'):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang={lang}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                temp = data['main']['temp']
                lat, lon = data['coord']['lat'], data['coord']['lon']
                air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}"
                async with session.get(air_url) as air_resp:
                    air_data = await air_resp.json()
                    aqi = air_data['list'][0]['main']['aqi']
                
                aqi_map = {1: "Excellent", 2: "Good", 3: "Fair", 4: "Poor", 5: "Very Poor"}
                return f"📍 {city}: {temp}°C\n💨 {MESSAGES[lang]['air']}: {aqi_map.get(aqi, 'N/A')}"
            return "City not found / Город не найден"

# --- КЛАВИАТУРЫ ---
def get_main_kb(lang='ru'):
    kb = [
        [KeyboardButton(text=MESSAGES[lang]['weather'])],
        [KeyboardButton(text=MESSAGES[lang]['tasks']), KeyboardButton(text=MESSAGES[lang]['lang'])]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_lang_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="set_lang_ru")],
        [InlineKeyboardButton(text="English 🇺🇸", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="Italiano 🇮🇹", callback_data="set_lang_it")]
    ])

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Выберите язык / Choose language / Scegli la lingua:", reply_markup=get_lang_inline())

@dp.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback: types.CallbackQuery):
    lang = callback.data.split("_")[-1]
    # Здесь можно добавить сохранение в БД, но для теста просто выдаем меню
    await callback.message.answer(MESSAGES[lang]['start'], reply_markup=get_main_kb(lang))
    await callback.answer()

@dp.message(F.text.in_({"🌤 Погода и Воздух", "🌤 Weather & Air", "🌤 Meteo e Aria"}))
async def ask_city(message: types.Message):
    await message.answer("Введите название города:")

@dp.message()
async def handle_text(message: types.Message):
    # Простая проверка: если это не команда, считаем за город
    res = await get_weather(message.text)
    await message.answer(res)

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web_server())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())