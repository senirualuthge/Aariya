from habit_db import get_db
from datetime import datetime, timedelta

def get_all_stats():
    with get_db() as conn:
        habits = conn.execute("SELECT id, name FROM habits").fetchall()
        stats = {}
        for habit in habits:
            completions = conn.execute(
                "SELECT date FROM completions WHERE habit_id = ? ORDER BY date DESC",
                (habit['id'],)
            ).fetchall()
            dates = [datetime.strptime(row['date'], '%Y-%m-%d') for row in completions]
            streak = calculate_streak(dates)
            stats[habit['name']] = streak
        return stats

def calculate_streak(dates):
    if not dates:
        return 0

    # Sort dates descending just in case
    sorted_dates = sorted(dates, reverse=True)
    
    today = datetime.today().date()
    last_done = sorted_dates[0].date()
    
    # If the last completion was more than 1 day ago, the streak is broken
    if (today - last_done).days > 1:
        return 0

    streak = 1
    for i in range(1, len(sorted_dates)):
        delta = (sorted_dates[i-1] - sorted_dates[i]).days
        if delta == 1:
            streak += 1
        elif delta == 0:
            continue # Skip double entries on same day if any
        else:
            break
    return streak
