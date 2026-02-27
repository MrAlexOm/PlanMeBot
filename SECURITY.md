# 🔒 Безопасность PlanMeBot

## ⚠️ КРИТИЧЕСКИЕ ПРАВИЛА БЕЗОПАСНОСТИ

### 1. НИКОГДА не храните токены в коде
- ❌ `API_TOKEN = "8465020533:AAGulNiI2bL_v0xlAAxpqhRfIXVaTsKWP1Y"`
- ✅ `API_TOKEN = os.getenv("BOT_TOKEN")`

### 2. Всегда используйте .env файлы
- Создайте `.env` файл в корне проекта
- Добавьте `.env` в `.gitignore`
- Используйте `.env.example` как шаблон

### 3. Проверьте .gitignore
Убедитесь, что `.gitignore` содержит:
```
.env
*.log
__pycache__/
*.db
```

### 4. Если токен попал в GitHub
1. **Немедленно отозвите токен** в @BotFather
2. **Сгенерируйте новый токен**
3. **Удалите токен из истории коммитов**:
   ```bash
   git filter-branch --force --index-filter 'git rm --cached --ignore-unmatch filename.py' --prune-empty --tag-name-filter cat -- --all
   git push origin --force --all
   ```

### 5. Регулярная проверка
- Проверяйте историю коммитов на наличие токенов
- Используйте `git log -p` для поиска чувствительных данных
- Рассмотрите использование pre-commit hooks

## 🛡️ Рекомендуемые практики

### Переменные окружения
```bash
# .env (никогда в Git!)
BOT_TOKEN=your_telegram_bot_token
WEATHER_API_KEY=your_openweather_api_key
GEMINI_API_KEY=your_gemini_api_key
```

### Код должен быть безопасным
```python
# ✅ Правильно
from dotenv import load_dotenv
load_dotenv()

API_TOKEN = os.getenv("BOT_TOKEN")
if not API_TOKEN:
    raise ValueError("BOT_TOKEN не найден!")

# ❌ НЕПРАВИЛЬНО
API_TOKEN = "real_token_here"
```

### Pre-commit hook (рекомендуется)
```bash
#!/bin/sh
# .git/hooks/pre-commit
if git diff --cached --name-only | grep -q ".env"; then
    echo "❌ .env файл не должен быть в коммите!"
    exit 1
fi
```

## 🚨 Что делать при компрометации

1. **Отозвать все токены**
2. **Сменить пароли** (если связаны)
3. **Проверить логи доступа**
4. **Очистить историю коммитов**
5. **Сообщить пользователям** (если необходимо)

---

**Помните: Безопасность - это ответственность каждого разработчика!**
