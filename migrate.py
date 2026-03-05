"""
Миграция: добавление поля city в таблицу users, поля recurrence в таблицу reminders и поля last_horoscope_date в таблицу users
Запустить: python migrate.py
"""
import asyncio
import aiosqlite

DB_PATH = "scheduler.db"


async def migrate():
    async with aiosqlite.connect(DB_PATH) as db:
        # Миграция таблицы users - добавление колонки city
        print("Проверяем таблицу users...")
        cursor = await db.execute("PRAGMA table_info(users)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'city' not in column_names:
            print("Добавляем колонку 'city' в таблицу users...")
            await db.execute("ALTER TABLE users ADD COLUMN city TEXT DEFAULT 'UTC'")
            await db.commit()
            print("✅ Колонка 'city' успешно добавлена в таблицу users!")
        else:
            print("Колонка 'city' уже существует в таблице users.")
        
        # Миграция таблицы users - добавление колонки last_horoscope_date
        if 'last_horoscope_date' not in column_names:
            print("Добавляем колонку 'last_horoscope_date' в таблицу users...")
            await db.execute("ALTER TABLE users ADD COLUMN last_horoscope_date DATE")
            await db.commit()
            print("✅ Колонка 'last_horoscope_date' успешно добавлена в таблицу users!")
        else:
            print("Колонка 'last_horoscope_date' уже существует в таблице users.")
        
        # Миграция таблицы reminders - добавление колонки recurrence
        print("\nПроверяем таблицу reminders...")
        cursor = await db.execute("PRAGMA table_info(reminders)")
        columns = await cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        if 'recurrence' not in column_names:
            print("Добавляем колонку 'recurrence' в таблицу reminders...")
            await db.execute("ALTER TABLE reminders ADD COLUMN recurrence VARCHAR(50)")
            await db.commit()
            print("✅ Колонка 'recurrence' успешно добавлена в таблицу reminders!")
        else:
            print("Колонка 'recurrence' уже существует в таблице reminders.")
        
        print("\n🎉 Все миграции завершены успешно!")


if __name__ == "__main__":
    asyncio.run(migrate())
