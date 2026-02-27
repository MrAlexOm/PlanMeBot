import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, insert, update, delete
from models import User, Reminder, Base
from datetime import datetime
from typing import Optional, List

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
    """Инициализация БД - создание всех таблиц"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized successfully")

# --- Классы для работы с сессиями ---

class UserRepository:
    """Репозиторий для работы с пользователями"""
    
    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
        """Получение пользователя по ID"""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_lang(session: AsyncSession, user_id: int) -> str:
        """Получение языка пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        return user.lang if user else 'en'
    
    @staticmethod
    async def set_lang(session: AsyncSession, user_id: int, lang: str) -> User:
        """Установка языка пользователя"""
        user = await UserRepository.get_by_id(session, user_id)
        if user:
            user.lang = lang
        else:
            user = User(id=user_id, lang=lang)
            session.add(user)
        
        await session.commit()
        logger.info(f"User {user_id} language set to {lang}")
        return user
    
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

class ReminderRepository:
    """Репозиторий для работы с напоминаниями"""
    
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int, 
        task_text: str, 
        remind_at: datetime, 
        city: Optional[str] = None
    ) -> Reminder:
        """Создание нового напоминания"""
        reminder = Reminder(
            user_id=user_id,
            task_text=task_text,
            remind_at=remind_at,
            city=city
        )
        session.add(reminder)
        await session.commit()
        await session.refresh(reminder)
        logger.info(f"Created reminder {reminder.id} for user {user_id}")
        return reminder
    
    @staticmethod
    async def get_user_reminders(
        session: AsyncSession, 
        user_id: int, 
        active_only: bool = True
    ) -> List[Reminder]:
        """Получение всех напоминаний пользователя"""
        query = select(Reminder).where(Reminder.user_id == user_id)
        
        if active_only:
            query = query.where(Reminder.is_completed == False)
        
        query = query.order_by(Reminder.remind_at)
        
        result = await session.execute(query)
        return result.scalars().all()
    
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
