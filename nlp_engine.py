"""
NLP Engine для обработки естественного языка через Groq API
"""
import os
import json
import logging
import asyncio
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Конфигурация Groq с безопасным импортом
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
client = None

try:
    from groq import AsyncGroq
    logger.info("[nlp_engine] - Loading Groq key...")
    
    if GROQ_API_KEY:
        client = AsyncGroq(api_key=GROQ_API_KEY)
        logger.info("[nlp_engine] - AsyncGroq API configured successfully")
    else:
        logger.error("[nlp_engine] - GROQ_API_KEY not found in environment variables")
        print("Где ключ, Лебовски?")
        
except ImportError as e:
    logger.error(f"[nlp_engine] - Failed to import AsyncGroq: {e}")
    logger.warning("[nlp_engine] - Horoscope functionality will be disabled")
    print("Где ключ, Лебовски?")
except Exception as e:
    logger.error(f"[nlp_engine] - Error initializing AsyncGroq: {e}")
    print("Где ключ, Лебовски?")

# Инициализация модели
model = "llama-3.1-8b-instant"
rate_limit_until = 0  # Время до которого не делать запросы (кэширование 429)

async def parse_task(text: str) -> dict:
    """
    Отправляет текст пользователя в Gemini для извлечения задач, дат и времени.
    Поддерживает как одну задачу, так и несколько задач в одном сообщении.
    С кэшированием Rate Limit и задержкой для обхода лимитов.
    
    Args:
        text: Текст сообщения пользователя
        
    Returns:
        dict: {
            'tasks': [
                {
                    'task': str,
                    'date': str or None,
                    'time': str or None,
                    'city': str or None,
                    'recurrence': str or None,
                    'is_complete_data': bool
                }
            ],
            'success': bool,
            'error': str or None,
            'original_text': str  # Сохраняем оригинальный текст для FSM
        }
    """
    global rate_limit_until
    
    # Проверяем кэширование Rate Limit (1 минута)
    current_time_check = asyncio.get_event_loop().time()
    if current_time_check < rate_limit_until:
        remaining = int(rate_limit_until - current_time_check)
        logger.warning(f"Rate Limit cached: skipping API call for {remaining}s")
        return {
            'tasks': [],
            'success': False,
            'error': f'Rate limit cached - wait {remaining}s',
            'original_text': text
        }
    
    if not client:
        logger.error("Groq client not initialized")
        return {
            'tasks': [],
            'success': False,
            'error': 'Groq API not configured',
            'original_text': text
        }
    
    # Промт для Groq
    today = datetime.now().strftime('%Y-%m-%d')
    tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    day_after = (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%H:%M')
    current_weekday = datetime.now().strftime('%A')
    
    system_instruction = f"""Ты - интеллектуальный парсер задач для бота-напоминалки. Текущая дата: {today}, текущее время: {current_time}, сегодняшний день: {current_weekday}.

Извлеки из текста пользователя ВСЕ задачи для создания напоминаний. В сообщении может быть одна или несколько задач.

Текст пользователя: "{text}"

Верни ответ СТРОГО в формате JSON:
{{
    "tasks": [
        {{
            "task": "чистый текст задачи без слов 'напомни', 'сегодня', 'завтра' и т.д.",
            "date": "YYYY-MM-DD" или null,
            "time": "HH:MM" или null,
            "city": "название города" или null,
            "recurrence": "daily/weekly/weekdays" или null,
            "is_complete_data": true/false
        }}
    ]
}}

Правила извлечения данных:
1. ЗАДАЧА (task): 
   - Только суть действия ("Выпить чаю", "Купить хлеб")
   - УДАЛИ слова: "Напомни", "напомни мне", "нужно", "надо", "пора"
   - УДАЛИ указания времени: "сегодня", "завтра", "в 15:00", "вечером"
   - УДАЛИ указания дат: "завтра", "послезавтра", "в понедельник"
   - В базе должна остаться только чистая задача

2. ДАТА (date) - КРИТИЧЕСКИ ВАЖНО:
   - Сегодняшняя дата: {today}. Если пользователь говорит 'сегодня', используй именно эту дату.
   - Если сказано 'завтра' → используй дату: {tomorrow}
   - Если сказано 'послезавтра' → используй: {day_after}
   - ВСЕГДА возвращай дату в формате YYYY-MM-DD, никогда не null если дата указана в тексте

3. ВРЕМЯ (time) - КРИТИЧЕСКИ ВАЖНО:
   - Текущее время: {current_time}
   - Если сказано 'в 15:00' или 'в 3 часа дня' → верни '15:00'
   - Если сказано 'в 20:00' → верни '20:00'
   - Если сказано 'утром' → верни '09:00'
   - Если сказано 'днем' → верни '14:00'
   - Если сказано 'вечером' → верни '19:00'
   - ВСЕГДА возвращай время в формате HH:MM, никогда не null если время указано в тексте

4. ГОРОД (city): Извлеки если упомянут ("в Тбилиси", "в Москве").

5. ПОВТОРЕНИЕ (recurrence) - определяй если указано:
   - Если сказано "каждый день", "ежедневно", "every day", "ogni giorno" → верни "daily"
   - Если сказано "каждую неделю", "раз в неделю", "every week", "ogni settimana" → верни "weekly"
   - Если сказано "по будням", "на рабочие дни", "weekdays", "feriali" → верни "weekdays"
   - Если повторение не указано → верни null

Примеры очистки текста задачи:
- "Напомни выпить чаю сегодня в 20:00" → task: "Выпить чаю"
- "Нужно купить хлеб завтра в 12:00" → task: "Купить хлеб"
- "купить молоко сегодня вечером" → task: "Купить молоко"

Ответ только JSON, без дополнительного текста."""

    try:
        logger.info(f"Sending text to Groq: {text[:50]}...")
        
        # Добавляем задержку чтобы избежать "зажима" лимитов
        await asyncio.sleep(1.5)
        
        # Используем Groq API
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text}
            ],
            temperature=0.1,
            max_tokens=1024
        )
        
        response_text = response.choices[0].message.content.strip()
        
        # Парсим ответ
        logger.info(f"Groq raw response: {response_text}")
        print(f">>> Raw Groq Response: {response_text}")
        
        # Убираем markdown код если есть
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        
        response_text = response_text.strip()
        
        # Парсим JSON
        result = json.loads(response_text)
        print(f">>> Parsed JSON: {result}")
        
        # Проверяем формат ответа - должен быть массив tasks
        if 'tasks' not in result:
            # Если пришел старый формат с одной задачей - конвертируем
            if 'task' in result:
                result['tasks'] = [{
                    'task': result.get('task'),
                    'date': result.get('date'),
                    'time': result.get('time'),
                    'city': result.get('city'),
                    'recurrence': result.get('recurrence'),
                    'is_complete_data': result.get('is_complete_data', False)
                }]
            else:
                raise ValueError("Missing 'tasks' field in response")
        
        # Обрабатываем каждую задачу в массиве
        for task in result['tasks']:
            # Добавляем city если отсутствует
            if 'city' not in task:
                task['city'] = None
            
            # Добавляем recurrence если отсутствует
            if 'recurrence' not in task:
                task['recurrence'] = None
            
            # Добавляем is_complete_data если отсутствует
            if 'is_complete_data' not in task:
                task['is_complete_data'] = bool(
                    task.get('task') and 
                    task.get('date') and 
                    task.get('time')
                )
            
            # Валидация даты
            if task.get('date') and task['date'] != 'null':
                try:
                    datetime.strptime(task['date'], '%Y-%m-%d')
                    # Дата валидна - оставляем как есть
                except ValueError:
                    logger.warning(f"Invalid date format: {task['date']}")
                    task['date'] = None
            elif task.get('date') == 'null':
                task['date'] = None
                
            # Валидация времени
            if task.get('time') and task['time'] != 'null':
                try:
                    datetime.strptime(task['time'], '%H:%M')
                    # Время валидно - оставляем как есть
                except ValueError:
                    logger.warning(f"Invalid time format: {task['time']}")
                    task['time'] = None
            elif task.get('time') == 'null':
                task['time'] = None
        
        result['success'] = True
        result['error'] = None
        
        tasks_count = len(result['tasks'])
        logger.info(f"Parsed {tasks_count} tasks from Gemini")
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response as JSON: {e}")
        return {
            'tasks': [],
            'success': False,
            'error': f'JSON parse error: {e}',
            'original_text': text
        }
    except Exception as e:
        error_msg = str(e)
        # Проверяем на ошибку 429 (Quota exceeded / Rate limit)
        if '429' in error_msg or 'Quota exceeded' in error_msg or 'Rate limit' in error_msg or 'Resource has been exhausted' in error_msg:
            logger.warning(f"Gemini Rate Limit (429): {error_msg}")
            # Устанавливаем кэш на 60 секунд
            rate_limit_until = asyncio.get_event_loop().time() + 60
            logger.info(f"Rate Limit cached until: {rate_limit_until}")
            return {
                'tasks': [],
                'success': False,
                'error': 'Rate limit exceeded - falling back to FSM',
                'original_text': text
            }
        logger.error(f"Gemini API error: {e}")
        return {
            'tasks': [],
            'success': False,
            'error': str(e),
            'original_text': text
        }


async def generate_horoscope(zodiac_sign: str, birth_date: str, city: str, lang: str) -> str:
    """Генерирует персонализированный гороскоп с помощью Groq"""
    # Проверяем наличие API ключа
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        error_msg = "GROQ_API_KEY not found in environment variables"
        logger.error(f"[nlp_engine] - {error_msg}")
        print("Где ключ, Лебовски?")
        raise Exception(error_msg)
    
    # Создаем клиент напрямую с API ключом
    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=api_key)
        logger.info(f"[nlp_engine] - Created AsyncGroq client for {zodiac_sign}")
    except Exception as e:
        error_msg = f"Failed to create AsyncGroq client: {e}"
        logger.error(f"[nlp_engine] - {error_msg}")
        print("Где ключ, Лебовски?")
        raise Exception(error_msg)
    
    try:
        # Получаем текущую дату для точного гороскопа
        import datetime
        import pytz
        current_date = datetime.datetime.now(pytz.UTC).strftime("%Y-%m-%d")
        
        # Создаем эмоциональный и вдохновляющий промпт с инструкциями по форматированию и эмодзи
        if lang == 'ru':
            prompt = f"Сегодня {current_date}. Создай персонализированный, вдохновляющий гороскоп для {zodiac_sign} (родился {birth_date}) на сегодня. Язык: Русский. Пользователь сейчас в городе {city}. Стиль: Эмоциональный, дружелюбный, позитивный. Обязательно добавь минимум 2-3 эмодзи в текст для выражения эмоций (✨🌟💫🔮💖⭐). Используй HTML-теги: <b> для жирного текста, <i> для курсива. В конце сообщения, после специального разделителя |||, добавь ОДНО английское слово, описывающее 'вайб' дня (например: success, love, energy, harmony, magic, luck). Пример: '...тебя ждет удача во всех делах|||success'"
        elif lang == 'en':
            prompt = f"Today is {current_date}. Create a personalized, inspiring horoscope for {zodiac_sign} (born {birth_date}) for today. Language: English. User is currently in {city}. Style: Emotional, friendly, positive. Include minimum 2-3 emojis throughout the text to express emotions (✨🌟💫🔮💖⭐). Use HTML tags: <b> for bold text, <i> for italics. At the end of the message, after the special separator |||, add ONE English word describing the day's 'vibe' (e.g., success, love, energy, harmony, magic, luck). Example: '...success awaits you in all endeavors|||success'"
        elif lang == 'it':
            prompt = f"Oggi è {current_date}. Crea un oroscopo personalizzato, ispiratore per {zodiac_sign} (nato {birth_date}) per oggi. Lingua: Italiano. L'utente è attualmente nella città {city}. Stile: Emotivo, amichevole, positivo. Includi minimo 2-3 emoji nel testo per esprimere emozioni (✨🌟💫🔮💖⭐). Usa tag HTML: <b> per testo grassetto, <i> per corsivo. Alla fine del messaggio, dopo il separatore speciale |||, aggiungi UNA parola inglese che descrive la 'vibrazione' del giorno (es. success, love, energy, harmony, magic, luck). Esempio: '...il successo ti aspetta in tutte le imprese|||success'"
        else:
            prompt = f"Today is {current_date}. Create a personalized, inspiring horoscope for {zodiac_sign} (born {birth_date}) for today. Language: Russian. User is currently in {city}. Style: Emotional, friendly, positive. Include minimum 2-3 emojis throughout the text to express emotions (✨🌟💫🔮💖⭐). Use HTML tags: <b> for bold text, <i> for italics. At the end of the message, after the special separator |||, add ONE English word describing the day's 'vibe' (e.g., success, love, energy, harmony, magic, luck). Example: '...success awaits you in all endeavors|||success'"
        
        logger.info(f"[nlp_engine] - Sending request to Groq for {zodiac_sign} on {current_date}")
        print(f"[nlp_engine] - Prompt: {prompt}")
        
        # Генерируем контент с помощью AsyncGroq
        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a professional astrologer with many years of experience, creating accurate and inspiring horoscopes. Use simple HTML tags like <b> for bold and <i> for italics instead of Markdown formatting."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800  # Increased to 800 for even more complete horoscope text
        )
        
        horoscope_text = response.choices[0].message.content.strip()
        
        # Проверяем, что ответ не пустой
        if not horoscope_text:
            error_msg = "Groq returned empty response"
            logger.error(f"[nlp_engine] - {error_msg}")
            raise Exception(error_msg)
        
        logger.info(f"[nlp_engine] - Successfully generated horoscope for {zodiac_sign}: {horoscope_text[:50]}...")
        return horoscope_text
        
    except Exception as e:
        logger.error(f"[nlp_engine] - Error generating horoscope: {e}")
        logger.error(f"[nlp_engine] - Error details: {type(e).__name__}: {str(e)}")
        # Передаем реальную ошибку наверх для логирования
        raise e


# Для тестирования
if __name__ == "__main__":
    # Тестовые примеры
    test_texts = [
        "Напомни мне купить молоко завтра в 15:00",
        "Встреча с клиентом 25 декабря в 14:30",
        "Позвонить маме",
        "Записаться к врачу на следующий вторник в 10:00"
    ]
    
    async def test():
        for text in test_texts:
            print(f"\nInput: {text}")
            result = await parse_task(text)
            print(f"Result: {result}")
    
    import asyncio
    asyncio.run(test())
