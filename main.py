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
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY") # Не забудь добавить в Render!

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ТЕКСТЫ И ЯЗЫКИ ---
MESSAGES = {
    'ru': {
        'start': "Привет! Я твой продвинутый помощник. Я умею планировать задачи и показывать погоду.",
        'weather_btn': "🌤 Погода и Воздух",
        'task_btn': "📅 Задачи",
        'lang_btn': "🌐 Сменить язык",
        'choose_city': "Напишите название города:",
        'air_quality': "Качество воздуха"
    },
    'en': {
        'start': "Hello! I'm your advanced assistant. I can manage tasks and show weather.",
        'weather_btn': "🌤 Weather & Air",
        'task_btn': "📅 Tasks",
        'lang_btn': "🌐 Change Language",
        'choose_city': "Type the city name:",
        'air_quality': "Air Quality"
    }
}

# --- БЛОК RENDER (АНТИ-СОН) ---
async def handle(request):
    return web.Response(text="PlanMe is Alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()

# --- ПОГОДА И ВОЗДУХ ---
async def get_weather(city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric&lang=ru"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                temp = data['main']['temp']
                desc = data['weather'][0]['description']
                # Запрос качества воздуха (Air Pollution API)
                lat, lon = data['coord']['lat'], data['coord']['lon']
                air_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={WEATHER_API_KEY}"
                async with session.get(air_url) as air_resp:
                    air_data = await air_resp.json()
                    aqi = air_data['list'][0]['main']['aqi']
                return f"📍 {city}: {temp}°C, {desc}\nИндекс воздуха: {aqi}/5"
            return "Город не найден 🤷‍♂️"

# --- КЛАВИАТУРЫ ---
def get_main_kb(lang='ru'):
    kb = [
        [KeyboardButton(text=MESSAGES[lang]['weather_btn'])],
        [KeyboardButton(text=MESSAGES[lang]['task_btn']), KeyboardButton(text=MESSAGES[lang]['lang_btn'])]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Тут можно добавить логику сохранения языка в БД, пока по дефолту RU
    await message.answer(MESSAGES['ru']['start'], reply_markup=get_main_kb('ru'))

@dp.message(F.text.contains("Погода") | F.text.contains("Weather"))
async def ask_city(message: types.Message):
    await message.answer("Введите город (например: Москва или Tbilisi):")

@dp.message(F.text == "🌐 Сменить язык" or F.text == "🌐 Change Language")
async def change_lang(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru"),
         InlineKeyboardButton(text="English 🇺🇸", callback_data="lang_en")]
    ])
    await message.answer("Выберите язык / Choose language:", reply_markup=kb)

@dp.message()
async def common_handler(message: types.Message):
    # Если это похоже на название города (просто текст)
    weather_info = await get_weather(message.text)
    await message.answer(weather_info)

# --- ЗАПУСК ---
async def main():
    asyncio.create_task(start_web_server())
    logging.info("Starting PlanMe Mega Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())