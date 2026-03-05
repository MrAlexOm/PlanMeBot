from sqlalchemy import Column, Integer, BigInteger, String, Text, Boolean, DateTime, ForeignKey, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True)  # Telegram user_id
    lang = Column(String(2), default='en')      # ru, en, it
    city = Column(String(100), default='UTC')    # User's default city for timezone
    timezone = Column(String(50), default='UTC') # для будущих фич
    birth_date = Column(String(10), nullable=True)  # Birth date in DD.MM.YYYY format
    last_horoscope_date = Column(Date, nullable=True)  # Last date user got horoscope
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с задачами
    reminders = relationship("Reminder", back_populates="user", cascade="all, delete-orphan")

class Reminder(Base):
    __tablename__ = 'reminders'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, ForeignKey('users.id'), nullable=False)
    task_text = Column(Text, nullable=False)
    remind_at = Column(DateTime, nullable=False)  # UTC время
    city = Column(String(100))
    recurrence = Column(String(50))  # daily, weekly, weekdays, none
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с пользователем
    user = relationship("User", back_populates="reminders")
