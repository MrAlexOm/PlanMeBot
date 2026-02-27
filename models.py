from sqlalchemy import Column, Integer, BigInteger, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(BigInteger, primary_key=True)  # Telegram user_id
    lang = Column(String(2), default='en')      # ru, en, it
    timezone = Column(String(50), default='UTC') # для будущих фич
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
    is_completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Связь с пользователем
    user = relationship("User", back_populates="reminders")
