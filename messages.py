# Централизованные сообщения для мультиязычности

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
        'reminder_text': "🔔 НАПОМИНАНИЕ: {note}\n\n📍 Город: {city}\n🌤 Погода: {temp}°C, {desc}\n💨 Качество воздуха: {aqi}",
        'error_city': "Не удалось найти такой город. Проверьте название и попробуйте снова.",
        'error_date': "Некорректная дата. Пожалуйста, выберите одну из предложенных кнопок.",
        'error_time': "Некорректный формат времени. Введите в формате ЧЧ:ММ, например, 14:30.",
        'language_changed': "Язык изменен на {lang}"
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
        'reminder_text': "🔔 REMINDER: {note}\n\n📍 City: {city}\n🌤 Weather: {temp}°C, {desc}\n💨 Air Quality: {aqi}",
        'error_city': "Could not find this city. Please check the name and try again.",
        'error_date': "Invalid date. Please choose one of the suggested options.",
        'error_time': "Invalid time format. Use HH:MM, e.g., 14:30.",
        'language_changed': "Language changed to {lang}"
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
        'reminder_text': "🔔 PROMEMORIA: {note}\n\n📍 Città: {city}\n🌤 Meteo: {temp}°C, {desc}\n💨 Qualità dell'aria: {aqi}",
        'error_city': "Impossibile trovare questa città. Controlla il nome e riprova.",
        'error_date': "Data non valida. Scegli una delle opzioni proposte.",
        'error_time': "Formato orario non valido. Usa HH:MM, ad es., 14:30.",
        'language_changed': "Lingua cambiata a {lang}"
    }
}

# Названия языков для сообщений
LANGUAGE_NAMES = {
    'ru': 'Русский',
    'en': 'English',
    'it': 'Italiano'
}
