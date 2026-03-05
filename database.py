import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, func, insert, update, delete
from models import User, Reminder, Base
from datetime import date, datetime
from typing import Optional, List
import pytz

# Настройки БД
DATABASE_URL = "sqlite+aiosqlite:///scheduler.db"

# Создание асинхронного движка
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Выставить True для отладки SQL-запросов
    future=True
)

# Создание фабрики сессий
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

logger = logging.getLogger(__name__)

async def init_db():
    """Инициализация БД - создание всех таблиц и проверка колонок"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Проверяем и добавляем недостающие колонки
    await check_and_migrate_columns()
    
    logger.info("Database initialized successfully")

async def check_and_migrate_columns():
    """Проверяет существование колонок и выполняет миграции при необходимости"""
    from sqlalchemy import text
    
    async with engine.begin() as conn:
        try:
            # Проверяем и добавляем birth_date если отсутствует
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN birth_date VARCHAR(10)"))
                logger.info("birth_date column added successfully")
            except Exception as e:
                if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                    logger.info("birth_date column already exists")
                else:
                    logger.error(f"Error adding birth_date column: {e}")
                    raise
            
            # Проверяем и добавляем last_horoscope_date если отсутствует
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN last_horoscope_date DATE"))
                logger.info("last_horoscope_date column added successfully")
            except Exception as e:
                if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                    logger.info("last_horoscope_date column already exists")
                else:
                    logger.error(f"Error adding last_horoscope_date column: {e}")
                    raise
            
            # Проверяем и добавляем timezone если отсутствует
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN timezone VARCHAR(50) DEFAULT 'UTC'"))
                logger.info("timezone column added successfully")
            except Exception as e:
                if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
                    logger.info("timezone column already exists")
                else:
                    logger.error(f"Error adding timezone column: {e}")
                    raise
            
            logger.info("Column migration completed successfully")
            
        except Exception as e:
            logger.error(f"Error during column migration: {e}")
            # Не прерываем работу бота при ошибках миграции
            logger.warning("Continuing bot startup despite migration errors")

# --- Классы для работы с сессиями ---

class UserRepository:
    """Репозиторий для работы с пользователями"""
    
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """Получение пользователя по ID"""
        try:
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            logger.info(f"=== UserRepository.get_by_id: user_id={user_id}, found={user is not None}")
            return user
        except Exception as e:
            logger.error(f"=== UserRepository.get_by_id ОШИБКА: user_id={user_id}, error={e}")
            raise
    
    @staticmethod
    async def get_lang(session: AsyncSession, user_id: int) -> str:
        """Получение языка пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        return user.lang if user else 'en'
    
    @staticmethod
    async def set_lang(session: AsyncSession, user_id: int, lang: str) -> User:
        """Установка языка пользователя"""
        try:
            logger.info(f"=== UserRepository.set_lang: user_id={user_id}, lang={lang}")
            user = await UserRepository.get_by_id(session, user_id)
            if user:
                user.lang = lang
                logger.info(f"=== UserRepository.set_lang: обновляем язык существующего пользователя")
            else:
                user = User(id=user_id, lang=lang)
                session.add(user)
                logger.info(f"=== UserRepository.set_lang: создаем нового пользователя")
            
            await session.commit()
            logger.info(f"=== UserRepository.set_lang: commit успешен")
            logger.info(f"User {user_id} language set to {lang}")
            return user
        except Exception as e:
            logger.error(f"=== UserRepository.set_lang ОШИБКА: user_id={user_id}, error={e}")
            await session.rollback()
            raise
    
    @staticmethod
    async def get_or_create(session: AsyncSession, user_id: int, lang: str = 'en') -> User:
        """Получение или создание пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        
        if not user:
            user = User(id=user_id, lang=lang)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            logger.info(f"Created new user {user_id} with lang {lang}")
        
        return user
    
    @staticmethod
    async def set_city(session: AsyncSession, user_id: int, city: str) -> User:
        """Установка города пользователя"""
        try:
            logger.info(f"=== UserRepository.set_city: user_id={user_id}, city={city}")
            user = await UserRepository.get_by_id(session, user_id)
            if user:
                user.city = city
                logger.info(f"=== UserRepository.set_city: обновляем город существующего пользователя")
            else:
                user = User(id=user_id, city=city)
                session.add(user)
                logger.info(f"=== UserRepository.set_city: создаем нового пользователя с городом")
            
            await session.commit()
            await session.refresh(user)
            return user
        except Exception as e:
            logger.error(f"Error setting city: {e}")
            await session.rollback()
            raise
    
    @staticmethod
    async def get_timezone(session: AsyncSession, user_id: int) -> str:
        """Получение часового пояса пользователя"""
        try:
            user = await UserRepository.get_by_id(session, user_id)
            return user.timezone if user and user.timezone else 'UTC'
        except Exception as e:
            logger.error(f"Error getting timezone for user {user_id}: {e}")
            return 'UTC'

    @staticmethod
    async def get_city(session: AsyncSession, user_id: int) -> str:
        """Получение города пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        return user.city if user else 'UTC'
    
    @staticmethod
    async def set_birth_date(session: AsyncSession, user_id: int, birth_date: str) -> User:
        """Установка даты рождения пользователя"""
        try:
            logger.info(f"=== UserRepository.set_birth_date: user_id={user_id}, birth_date={birth_date}")
            user = await UserRepository.get_by_id(session, user_id)
            if user:
                user.birth_date = birth_date
                logger.info(f"=== UserRepository.set_birth_date: обновляем дату рождения существующего пользователя")
            else:
                user = User(id=user_id, birth_date=birth_date)
                session.add(user)
                logger.info(f"=== UserRepository.set_birth_date: создаем нового пользователя с датой рождения")
            
            await session.commit()
            await session.refresh(user)
            return user
        except Exception as e:
            logger.error(f"Error setting birth date: {e}")
            await session.rollback()
            raise
    
    @staticmethod
    async def get_birth_date(session: AsyncSession, user_id: int) -> str:
        """Получение даты рождения пользователя"""
        try:
            user = await UserRepository.get_by_id(session, user_id)
            return user.birth_date if user else None
        except Exception as e:
            logger.error(f"Error getting birth date: {e}")
            return None
    
    @staticmethod
    async def get_last_horoscope_date(session: AsyncSession, user_id: int) -> Optional[date]:
        """Получение даты последнего гороскопа пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        return user.last_horoscope_date if user else None
    
    @staticmethod
    async def set_last_horoscope_date(session: AsyncSession, user_id: int, horoscope_date: date) -> None:
        """Установка даты последнего гороскопа пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        if user:
            user.last_horoscope_date = horoscope_date
            await session.commit()

class ReminderRepository:
    """Репозиторий для работы с напоминаниями"""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int, 
        task_text: str, 
        remind_at: datetime, 
        city: Optional[str] = None,
        recurrence: Optional[str] = None
    ) -> Reminder:
        """Создание нового напоминания"""
        reminder = Reminder(
            user_id=user_id,
            task_text=task_text,
            remind_at=remind_at,
            city=city,
            recurrence=recurrence
        )
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)
        logger.info(f"Created reminder {reminder.id} for user {user_id} with recurrence={recurrence}")
        return reminder
    
    @staticmethod
    async def get_by_id(session: AsyncSession, reminder_id: int) -> Optional[Reminder]:
        """Получение напоминания по ID"""
        result = await session.execute(
            select(Reminder).where(Reminder.id == reminder_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_active_count(session: AsyncSession, user_id: int) -> int:
        """Получение количества активных напоминаний пользователя"""
        # Get current time in UTC
        now_utc = datetime.now(pytz.UTC)
        
        result = await session.execute(
            select(func.count(Reminder.id))
            .where(
                Reminder.user_id == user_id,
                Reminder.is_completed == False,
                Reminder.remind_at > now_utc
            )
        )
        return result.scalar()
    
    @staticmethod
    async def get_user_reminders_paginated(
        session: AsyncSession, 
        user_id: int, 
        active_only: bool = True,
        future_only: bool = True,
        page: int = 1,
        per_page: int = 5
    ) -> List[Reminder]:
        """Получение напоминаний пользователя с пагинацией"""
        from datetime import datetime
        import pytz
        
        query = select(Reminder).where(Reminder.user_id == user_id)
        
        if active_only:
            query = query.where(Reminder.is_completed == False)
        
        if future_only:
            # Get current time in UTC to compare with remind_at (which is stored in UTC)
            now_utc = datetime.now(pytz.UTC)
            query = query.where(Reminder.remind_at > now_utc)
        
        query = query.order_by(Reminder.remind_at)
        
        # Add pagination
        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    @staticmethod
    async def get_active_by_user(session: AsyncSession, user_id: int) -> List[Reminder]:
        """Получение активных (невыполненных) напоминаний пользователя"""
        return await ReminderRepository.get_user_reminders_paginated(session, user_id, active_only=True)
    
    @staticmethod
    async def mark_completed(session: AsyncSession, reminder_id: int) -> bool:
        """Отметить напоминание как выполненное"""
        try:
            reminder = await ReminderRepository.get_by_id(session, reminder_id)
            if reminder:
                reminder.is_completed = True
                await session.commit()
                logger.info(f"Marked reminder {reminder_id} as completed")
                return True
            else:
                logger.warning(f"Reminder {reminder_id} not found for completion")
                return False
        except Exception as e:
            logger.error(f"Error marking reminder {reminder_id} as completed: {e}")
            await session.rollback()
            return False
    
    @staticmethod
    async def get_pending_reminders(
        session: AsyncSession, 
        before_time: datetime
    ) -> List[Reminder]:
        """Получение напоминаний, которые нужно отправить"""
        result = await session.execute(
            select(Reminder)
            .where(
                Reminder.remind_at <= before_time,
                Reminder.is_completed == False
            )
            .order_by(Reminder.remind_at)
        )
        return result.scalars().all()
    
    @staticmethod
    async def mark_completed(session: AsyncSession, reminder_id: int) -> bool:
        """Отметить напоминание как выполненное"""
        result = await session.execute(
            update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(is_completed=True)
        )
        await session.commit()
        success = result.rowcount > 0
        if success:
            logger.info(f"Marked reminder {reminder_id} as completed")
        return success
    
    @staticmethod
    async def delete(session: AsyncSession, reminder_id: int, user_id: int) -> bool:
        """Удаление напоминания"""
        result = await session.execute(
            delete(Reminder)
            .where(Reminder.id == reminder_id, Reminder.user_id == user_id)
        )
        await session.commit()
        success = result.rowcount > 0
        if success:
            logger.info(f"Deleted reminder {reminder_id} for user {user_id}")
        return success
    
    @staticmethod
    async def get_last_reminder(session: AsyncSession, user_id: int) -> Optional[Reminder]:
        """Получение последнего напоминания пользователя"""
        result = await session.execute(
            select(Reminder)
            .where(Reminder.user_id == user_id)
            .order_by(Reminder.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

# --- Обратная совместимость ---

async def get_user_lang(user_id: int) -> str:
    """Обратная совместимая функция получения языка пользователя"""
    async with AsyncSessionLocal() as session:
        return await UserRepository.get_lang(session, user_id)

async def set_user_lang(user_id: int, lang: str) -> None:
    """Обратная совместимая функция установки языка пользователя"""
    async with AsyncSessionLocal() as session:
        await UserRepository.set_lang(session, user_id, lang)

async def get_or_create_user(user_id: int, lang: str = 'en') -> User:
    """Обратная совместимая функция получения/создания пользователя"""
    async with AsyncSessionLocal() as session:
        return await UserRepository.get_or_create(session, user_id, lang)

async def create_reminder(
    user_id: int, 
    task_text: str, 
    remind_at: datetime, 
    city: Optional[str] = None
) -> Reminder:
    """Обратная совместимая функция создания напоминания"""
    async with AsyncSessionLocal() as session:
        return await ReminderRepository.create(
            session, user_id, task_text, remind_at, city
        )

# --- Вспомогательные функции ---

async def close_db():
    """Закрытие соединения с БД"""
    await engine.dispose()
    logger.info("Database connection closed")
