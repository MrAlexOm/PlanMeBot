import sqlite3

def init_db():
    conn = sqlite3.connect('scheduler.db')
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS reminders 
                   (id INTEGER PRIMARY KEY, user_id INTEGER, task_text TEXT, remind_time TEXT, lang TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (user_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'en')''')
    conn.commit()
    conn.close()

def get_user_lang(user_id):
    conn = sqlite3.connect('scheduler.db')
    cur = conn.cursor()
    cur.execute("SELECT lang FROM users WHERE user_id = ?", (user_id,))
    res = cur.fetchone()
    conn.close()
    return res[0] if res else 'en'

def set_user_lang(user_id, lang):
    conn = sqlite3.connect('scheduler.db')
    cur = conn.cursor()
    cur.execute("INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang))
    conn.commit()
    conn.close()