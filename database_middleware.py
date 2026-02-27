"""
Middleware для автоматического управления сессиями SQLAlchemy в aiogram
"""
from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from database import AsyncSessionLocal
import logging

logger = logging.getLogger(__name__)

class DatabaseMiddleware(BaseMiddleware):
    """
    Middleware для автоматического создания и закрытия сессий БД
    """
    
    def __init__(self, session_pool: async_sessionmaker[AsyncSession]):
        self.session_pool = session_pool
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        """
        Создает сессию БД, передает ее в handler и автоматически закрывает
        """
        async with self.session_pool() as session:
            try:
                # Добавляем сессию в данные хендлера
                data["db_session"] = session
                logger.debug(f"Database session created for event: {type(event).__name__}")
                
                # Выполняем хендлер с сессией БД
                result = await handler(event, data)
                
                logger.debug(f"Database session closed successfully for event: {type(event).__name__}")
                return result
                
            except Exception as e:
                logger.error(f"Error in database middleware: {e}")
                # Сессия автоматически закроется благодаря async with
                raise
            finally:
                # Сессия автоматически закрывается при выходе из async with
                pass


# Фабрика для создания middleware с глобальной сессией
def create_database_middleware() -> DatabaseMiddleware:
    """Создает экземпляр middleware с глобальной сессией"""
    return DatabaseMiddleware(AsyncSessionLocal)


# Декоратор для удобного доступа к сессии в хендлерах
def with_db_session(func):
    """
    Декоратор для автоматического получения сессии из data
    Упрощает доступ к сессии в хендлерах
    """
    async def wrapper(event, data, *args, **kwargs):
        session = data.get("db_session")
        if not session:
            raise ValueError("No database session found in middleware data")
        
        # Добавляем сессию в kwargs для удобства
        kwargs["session"] = session
        return await func(event, data, *args, **kwargs)
    
    return wrapper
