"""
Продвинутое логирование для API запросов и операций бота
"""
import logging
import json
import time
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio

class APILogger:
    """Специализированный логгер для API запросов"""
    
    def __init__(self, name: str = "api"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Создаем форматер для детального логирования
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловый обработчик для API логов
        try:
            file_handler = logging.FileHandler(
                f'api_requests_{datetime.now().strftime("%Y%m%d")}.log',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception as e:
            print(f"Could not create API file logger: {e}")
    
    def log_request(self, method: str, url: str, headers: Optional[Dict] = None, 
                   params: Optional[Dict] = None, data: Optional[Dict] = None):
        """Логирование исходящего запроса"""
        log_data = {
            "type": "REQUEST",
            "method": method,
            "url": url,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if headers:
            # Скрываем чувствительные данные
            safe_headers = {k: v for k, v in headers.items() 
                          if k.lower() not in ['authorization', 'api-key', 'x-api-key']}
            log_data["headers"] = safe_headers
        
        if params:
            log_data["params"] = params
            
        if data:
            log_data["data"] = data
        
        self.logger.info(f"API Request: {json.dumps(log_data, ensure_ascii=False, indent=2)}")
    
    def log_response(self, status_code: int, response_data: Optional[Dict] = None, 
                    response_time: Optional[float] = None, url: Optional[str] = None):
        """Логирование ответа"""
        log_data = {
            "type": "RESPONSE",
            "status_code": status_code,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if url:
            log_data["url"] = url
            
        if response_time is not None:
            log_data["response_time_ms"] = round(response_time * 1000, 2)
        
        if response_data:
            # Ограничиваем размер лога для больших ответов
            if len(str(response_data)) > 1000:
                log_data["response_preview"] = str(response_data)[:1000] + "..."
            else:
                log_data["response_data"] = response_data
        
        level = logging.ERROR if status_code >= 400 else logging.INFO
        self.logger.log(level, f"API Response: {json.dumps(log_data, ensure_ascii=False, indent=2)}")
    
    def log_error(self, error: Exception, context: Optional[str] = None):
        """Логирование ошибок API"""
        log_data = {
            "type": "ERROR",
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if context:
            log_data["context"] = context
        
        self.logger.error(f"API Error: {json.dumps(log_data, ensure_ascii=False, indent=2)}", exc_info=True)

class BotLogger:
    """Логгер для операций бота"""
    
    def __init__(self, name: str = "bot"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Создаем форматер
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - [USER:%(user_id)s] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Файловый обработчик для логов бота
        try:
            file_handler = logging.FileHandler(
                f'bot_operations_{datetime.now().strftime("%Y%m%d")}.log',
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        except Exception as e:
            print(f"Could not create bot file logger: {e}")
    
    def log_user_action(self, user_id: int, action: str, details: Optional[Dict] = None):
        """Логирование действий пользователя"""
        log_data = {
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        if details:
            log_data["details"] = details
        
        # Используем extra для передачи user_id в форматер
        self.logger.info(f"{action}: {json.dumps(log_data, ensure_ascii=False)}", extra={"user_id": user_id})
    
    def log_reminder_created(self, user_id: int, reminder_id: int, task_text: str, remind_at: str):
        """Логирование создания напоминания"""
        self.log_user_action(user_id, "REMINDER_CREATED", {
            "reminder_id": reminder_id,
            "task_text": task_text[:100],  # Ограничиваем длину
            "remind_at": remind_at
        })
    
    def log_reminder_sent(self, user_id: int, reminder_id: int, success: bool):
        """Логирование отправки напоминания"""
        self.log_user_action(user_id, "REMINDER_SENT", {
            "reminder_id": reminder_id,
            "success": success
        })
    
    def log_language_change(self, user_id: int, old_lang: str, new_lang: str):
        """Логирование смены языка"""
        self.log_user_action(user_id, "LANGUAGE_CHANGED", {
            "old_lang": old_lang,
            "new_lang": new_lang
        })

# Декоратор для логирования времени выполнения функций
def log_execution_time(logger: logging.Logger):
    """Декоратор для логирования времени выполнения"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.debug(f"{func.__name__} executed in {execution_time:.2f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"{func.__name__} failed after {execution_time:.2f}s: {e}")
                raise
        
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.debug(f"{func.__name__} executed in {execution_time:.2f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"{func.__name__} failed after {execution_time:.2f}s: {e}")
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

# Глобальные экземпляры логгеров
api_logger = APILogger()
bot_logger = BotLogger()
