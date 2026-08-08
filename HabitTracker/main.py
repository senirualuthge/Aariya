import click
from habits import add_habit, complete_habit, list_habits
from stats import get_all_stats
from habit_db import init_db

@click.group()
def cli():
    """Habit Tracker CLI - Track your daily habits!"""
    pass

@cli.command()
@click.argument('name')
def add(name):
    """Add a new habit."""
    msg = add_habit(name)
    click.echo(msg)

@cli.command()
@click.argument('name')
def done(name):
    """Mark a habit as done for today."""
    msg = complete_habit(name)
    click.echo(msg)

@cli.command()
def list():
    """List all your habits."""
    habits = list_habits()
    if not habits:
        click.echo("No habits found. Add one with 'add' command!")
        return
    click.echo("\nYour Habits:")
    for habit in habits:
        last = habit['last_done'] or "Never"
        click.echo(f"- {habit['name']} (Last done: {last})")

@cli.command()
def stats():
    """View streaks for all habits."""
    stats_data = get_all_stats()
    if not stats_data:
        click.echo("No stats available. Start completing habits!")
        return
    click.echo("\nHabit Streaks:")
    for name, streak in stats_data.items():
        click.echo(f"- {name}: {streak} day streak")

if __name__ == '__main__':
    init_db()
    cli()
