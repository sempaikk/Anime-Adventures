"""Bounded reconciliation around the original attempt, not only the last screen."""

from datetime import datetime, timezone
from datetime import timedelta
import hashlib
import discord


async def recent_attempts(channel, attempted, *, store=None, key=None):
    cursor = '0'
    token = hashlib.sha256(str(key).encode()).hexdigest() if key is not None else None
    if store is not None and token:
        store.execute('''CREATE TABLE IF NOT EXISTS bot_history_windows(
            key TEXT PRIMARY KEY,attempted REAL NOT NULL,cursor TEXT NOT NULL)''')
        row=store.execute('SELECT attempted,cursor FROM bot_history_windows WHERE key=?',(token,)).fetchone()
        if row and row[0]==attempted:
            cursor=row[1]
    after = discord.Object(id=int(cursor)) if cursor!='0' else datetime.fromtimestamp(max(0, attempted-5), timezone.utc)
    # Discord pages automatically; oldest first keeps the original time boundary.
    count=0
    until = datetime.fromtimestamp(max(0, attempted), timezone.utc) + timedelta(minutes=5)
    before = discord.Object(id=discord.utils.time_snowflake(until, high=True))
    async for message in channel.history(limit=100 if token else 300, after=after, before=before, oldest_first=True):
        count+=1
        cursor=str(message.id)
        yield message
    if store is not None and token:
        with store:
            store.execute('INSERT OR REPLACE INTO bot_history_windows VALUES(?,?,?)', (token,attempted,cursor if count==100 else '0'))
            store.execute('DELETE FROM bot_history_windows WHERE rowid NOT IN(SELECT rowid FROM bot_history_windows ORDER BY attempted DESC LIMIT 8192)')
