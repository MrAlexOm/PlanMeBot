import logging
import sys
from datetime import datetime

def setup_logging():
    """Настройка логирования для проекта"""
    
    # Создаем форматер с временем и уровнем
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Настройка корневого логгера
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Файловый обработчик (опционально)
    try:
        file_handler = logging.FileHandler(
            f'planme_bot_{datetime.now().strftime("%Y%m%d")}.log',
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Could not create file logger: {e}")
    
    # Отключаем логирование от сторонних библиотек
    logging.getLogger('aiogram').setLevel(logging.WARNING)
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    
    logger.info("Logging system initialized")
    return logger
