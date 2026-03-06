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
from api_logger import api_logger, bot_logger, log_execution_time
from nlp_engine import parse_task

# Регистрация middleware для БД
from database_middleware import DatabaseMiddleware

class TaskStates(StatesGroup):
    waiting_for_note = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_city = State()
    waiting_for_birthdate = State()
    waiting_for_recurrence = State()

# --- НАСТРОЙКИ ---
# Загрузка токенов из .env файла (НИКОГДА не храните токены в коде!)
API_TOKEN = os.getenv("BOT_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# --- СЛОВАРЬ GIF-ДЛЯ ВАЙБА ---
VIBE_GIFS = {
    'success': 'https://media.giphy.com/media/v1.YXilKnWq6B2F6uT9/giphy.gif',
    'love': 'https://media.giphy.com/media/v1.YXx076EYp9q2/giphy.gif',
    'energy': 'https://media.giphy.com/media/v1.YXx0bEJl3g2/giphy.gif',
    'harmony': 'https://media.giphy.com/media/v1.YXx0cQl3g3/giphy.gif',
    'magic': 'https://media.giphy.com/media/v1.YXx0dFJl4g4/giphy.gif',
    'luck': 'https://media.giphy.com/media/v1.YXx0aHJl5g5/giphy.gif',
    'joy': 'https://media.giphy.com/media/v1.YXx0fKJl6g6/giphy.gif',
    'peace': 'https://media.giphy.com/media/v1.YXx0gLJl7g7/giphy.gif',
    'power': 'https://media.giphy.com/media/v1.YXx0hJl8g8/giphy.gif'
}

async def send_vibe_gif(message: types.Message, vibe: str, lang: str):
    """Отправляет GIF соответствующую вайбу дня"""
    try:
        # Ищем подходящий GIF
        gif_url = VIBE_GIFS.get(vibe.lower())
        
        if not gif_url:
            # Если GIF не найден, отправляем стандартный
            gif_url = VIBE_GIFS['success']
        
        # Локализованные сообщения
        gif_messages = {
            'ru': f'🎬 Твой вайб сегодня: {vibe.upper()}',
            'en': f'🎬 Your vibe today: {vibe.upper()}',
            'it': f'🎬 La tua vibrazione oggi: {vibe.upper()}'
        }
        
        # Отправляем GIF как анимированный документ
        await message.answer_animation(
            gif_url,
            caption=gif_messages.get(lang, gif_messages['ru'])
        )
        
        logger.info(f"Sent GIF for vibe '{vibe}' to user {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error sending GIF: {e}")
        # Если GIF не отправился, продолжаем без ошибки
        pass

# Проверка наличия токенов
# Проверка наличия токенов
if not API_TOKEN:
    raise ValueError("BOT_TOKEN не найден! Создайте .env файл с вашим токеном.")
if not WEATHER_API_KEY:
    raise ValueError("WEATHER_API_KEY не найден! Создайте .env файл с вашим API ключом.")

# Настройка логирования
logger = setup_logging()

# Создание бота и диспетчера (ТОЛЬКО ОДИН РАЗ!)
logger.info("Creating bot and dispatcher...")
bot = Bot(token=API_TOKEN)
logger.info("Bot created successfully")

dp = Dispatcher(storage=MemoryStorage())
logger.info("Dispatcher created successfully")

# Регистрация middleware для БД
logger.info("Registering database middleware...")
dp.update.middleware(DatabaseMiddleware(AsyncSessionLocal))
logger.info("Database middleware registered successfully")

# --- ЗАПУСК БОТА ---
async def main():
    """Основная функция запуска бота"""
    try:
        logger.info("Starting PlanMeBOT...")
        
        # Сброс вебхука для избежания конфликтов
        logger.info("Dropping pending webhook updates...")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleanup completed")
        
        # Инициализация БД
        logger.info("Initializing database...")
        await init_db()
        logger.info("Database initialized successfully")
        
        # Инициализация планировщика
        logger.info("Initializing scheduler...")
        scheduler = AsyncIOScheduler()
        scheduler.configure(
            jobstores={
                'default': SQLAlchemyJobStore(url='sqlite:///jobs.sqlite')
            },
            timezone='UTC',
            job_defaults={
                'coalesce': False,
                'max_instances': 3
            }
        )
        logger.info("Scheduler initialized successfully")
        
        # Запуск планировщика
        logger.info("Starting scheduler...")
        scheduler.start()
        logger.info("Scheduler started successfully")
        
        # Запуск бота
        logger.info("Starting bot polling...")
        await dp.start_polling(
            drop_pending_updates=True,
            allowed_updates=types.Update.MESSAGE | types.Update.CALLBACK_QUERY
        )
        
    except Exception as e:
        logger.error(f"Fatal error in main: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
