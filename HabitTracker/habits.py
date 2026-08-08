from habit_db import get_db
from datetime import datetime


def add_habit(name):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO habits (name, last_done) VALUES (?, ?)", (name, None))
        conn.commit()
    return f"Habit '{name}' added!"


def complete_habit(name):
    today = datetime.today().strftime('%Y-%m-%d')
    with get_db() as conn:
        habit = conn.execute("SELECT id, last_done FROM habits WHERE name = ?", (name,)).fetchone()
        if not habit:
            return f"Habit '{name}' not found."
        
        if habit['last_done'] == today:
            return f"Habit '{name}' already completed for today!"

        conn.execute("INSERT INTO completions (habit_id, date) VALUES (?, ?)", (habit['id'], today))
        conn.execute("UPDATE habits SET last_done = ? WHERE id = ?", (today, habit['id']))
        conn.commit()
    return f"Habit '{name}' marked as done for today!"


def list_habits():
    with get_db() as conn:
        habits = conn.execute("SELECT name, last_done FROM habits").fetchall()
        return [dict(row) for row in habits]