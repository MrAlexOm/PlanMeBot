"""
Utility functions for the PlanMeBOT
"""
from datetime import datetime

def get_zodiac_sign(date_str: str) -> str:
    """Определяет знак зодиака по дате в формате ДД.ММ.ГГГГ"""
    try:
        day, month, _ = map(int, date_str.split('.'))
    except (ValueError, IndexError):
        return "Неизвестно"
    
    if (month == 3 and day >= 21) or (month == 4 and day <= 19): 
        return "Овен"
    if (month == 4 and day >= 20) or (month == 5 and day <= 20): 
        return "Телец"
    if (month == 5 and day >= 21) or (month == 6 and day <= 20): 
        return "Близнецы"
    if (month == 6 and day >= 21) or (month == 7 and day <= 22): 
        return "Рак"
    if (month == 7 and day >= 23) or (month == 8 and day <= 22): 
        return "Лев"
    if (month == 8 and day >= 23) or (month == 9 and day <= 22): 
        return "Дева"
    if (month == 9 and day >= 23) or (month == 10 and day <= 22): 
        return "Весы"
    if (month == 10 and day >= 23) or (month == 11 and day <= 21): 
        return "Скорпион"
    if (month == 11 and day >= 22) or (month == 12 and day <= 21): 
        return "Стрелец"
    if (month == 12 and day >= 22) or (month == 1 and day <= 19): 
        return "Козерог"
    if (month == 1 and day >= 20) or (month == 2 and day <= 18): 
        return "Водолей"
    return "Рыбы"

def get_zodiac_sign_en(date_str: str) -> str:
    """Determines zodiac sign by date in format DD.MM.YYYY"""
    try:
        day, month, _ = map(int, date_str.split('.'))
    except (ValueError, IndexError):
        return "Unknown"
    
    if (month == 3 and day >= 21) or (month == 4 and day <= 19): 
        return "Aries"
    if (month == 4 and day >= 20) or (month == 5 and day <= 20): 
        return "Taurus"
    if (month == 5 and day >= 21) or (month == 6 and day <= 20): 
        return "Gemini"
    if (month == 6 and day >= 21) or (month == 7 and day <= 22): 
        return "Cancer"
    if (month == 7 and day >= 23) or (month == 8 and day <= 22): 
        return "Leo"
    if (month == 8 and day >= 23) or (month == 9 and day <= 22): 
        return "Virgo"
    if (month == 9 and day >= 23) or (month == 10 and day <= 22): 
        return "Libra"
    if (month == 10 and day >= 23) or (month == 11 and day <= 21): 
        return "Scorpio"
    if (month == 11 and day >= 22) or (month == 12 and day <= 21): 
        return "Sagittarius"
    if (month == 12 and day >= 22) or (month == 1 and day <= 19): 
        return "Capricorn"
    if (month == 1 and day >= 20) or (month == 2 and day <= 18): 
        return "Aquarius"
    return "Pisces"

def get_zodiac_sign_it(date_str: str) -> str:
    """Determina il segno zodiacale dalla data in formato GG.MM.AAAA"""
    try:
        day, month, _ = map(int, date_str.split('.'))
    except (ValueError, IndexError):
        return "Sconosciuto"
    
    if (month == 3 and day >= 21) or (month == 4 and day <= 19): 
        return "Ariete"
    if (month == 4 and day >= 20) or (month == 5 and day <= 20): 
        return "Toro"
    if (month == 5 and day >= 21) or (month == 6 and day <= 20): 
        return "Gemelli"
    if (month == 6 and day >= 21) or (month == 7 and day <= 22): 
        return "Cancro"
    if (month == 7 and day >= 23) or (month == 8 and day <= 22): 
        return "Leone"
    if (month == 8 and day >= 23) or (month == 9 and day <= 22): 
        return "Vergine"
    if (month == 9 and day >= 23) or (month == 10 and day <= 22): 
        return "Bilancia"
    if (month == 10 and day >= 23) or (month == 11 and day <= 21): 
        return "Scorpione"
    if (month == 11 and day >= 22) or (month == 12 and day <= 21): 
        return "Sagittario"
    if (month == 12 and day >= 22) or (month == 1 and day <= 19): 
        return "Capricorno"
    if (month == 1 and day >= 20) or (month == 2 and day <= 18): 
        return "Acquario"
    return "Pesci"
