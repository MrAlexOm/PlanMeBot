import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
WEATHER_KEY = os.getenv("WEATHER_API_KEY")

LOCALES = {
    'ru': {
        'start': "👋 Привет! Я твой Тайм-Архитектор. Помогу ничего не забыть!",
        'menu_add': "⚡ Быстрое дело",
        'menu_list': "📅 Мои задачи",
        'menu_lang': "⚙️ Язык / Lingua",
        'ask_task': "✍️ О чем напомнить? Просто напиши это!",
        'ask_date': "📅 На какой день ставим?",
        'today': "Сегодня",
        'tomorrow': "Завтра",
        'ask_time': "⏰ Во сколько? (Формат ЧЧ:ММ, например 15:30)",
        'ask_city': "🌍 Введите город для прогноза погоды (или /skip):",
        'success': "✅ Ок! Напомню {time}",
        'notify': "🔔 Хей! Пора для: {task}{weather}",
        'empty': "📭 У вас пока нет активных задач."
    },
    'en': {
        'start': "👋 Hi! I'm your Time Architect. I'll help you remember everything!",
        'menu_add': "⚡ Quick Task",
        'menu_list': "📅 My Agenda",
        'menu_lang': "⚙️ Language / Lingua",
        'ask_task': "✍️ What should I remind you about? Just type it below!",
        'ask_date': "📅 For which day?",
        'today': "Today",
        'tomorrow': "Tomorrow",
        'ask_time': "⏰ When? (Format HH:MM, e.g. 15:30)",
        'ask_city': "🌍 Enter city for weather forecast (or /skip):",
        'success': "✅ Ok! I'll remind you at {time}",
        'notify': "🔔 Hey! It's time for: {task}{weather}",
        'empty': "📭 You have no active tasks yet."
    },
    'it': {
        'start': "👋 Ciao! Sono il tuo Architetto del Tempo. Ti aiuterò a ricordare tutto!",
        'menu_add': "⚡ Promemoria rapido",
        'menu_list': "📅 I miei impegni",
        'menu_lang': "⚙️ Lingua / Language",
        'ask_task': "✍️ Cosa devo ricordarti? Scrivilo qui sotto!",
        'ask_date': "📅 Per quale giorno?",
        'today': "Oggi",
        'tomorrow': "Domani",
        'ask_time': "⏰ A che ora? (Formato OO:MM, es. 15:30)",
        'ask_city': "🌍 Inserisci la città per il meteo (o /skip):",
        'success': "✅ Ok! Ti avviserò alle {time}",
        'notify': "🔔 Ehi! È ora di: {task}{weather}",
        'empty': "📭 Non hai ancora impegni attivi."
    }
}