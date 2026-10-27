"""One-time, owner-authorized W/M/L reset for old community banner messages."""

from datetime import datetime, timezone

import discord

from community_hub import CENTRAL_GUILD_ID


class BannerVoteOrder:
    def __init__(self, votes):
        self.votes, self.bot, self.db = votes, votes.bot, votes.db
        self.cutoff = 0
        self.db.execute('''CREATE TABLE IF NOT EXISTS banner_vote_order_repairs(
            guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, message_id TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'clear', cleared INTEGER NOT NULL DEFAULT 0,
            seeded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(channel_id,message_id))''')
        self.db.commit()

    def prepare_scan(self):
        target = self.votes.relay.target(CENTRAL_GUILD_ID)
        if not target:
            return
        cutoff_key = 'banner-vote-order-cutoff:1'
        cutoff = self.bot.store.get(cutoff_key)
        if cutoff is None:
            cutoff = discord.utils.time_snowflake(
                datetime.fromtimestamp(self.votes.relay.clock(), timezone.utc), high=True)
            self.bot.store.set(cutoff_key, cutoff)
        self.cutoff = int(cutoff)
        key = 'banner-vote-order-scan:1:' + target['channel_id']
        if not self.bot.store.get(key):
            with self.db:
                self.db.execute('''UPDATE banner_vote_backfill SET before_id=NULL,done=0,
                    scanned=0,rated=0,skipped=0,next_scan=0 WHERE guild_id=? AND channel_id=?''',
                    (str(CENTRAL_GUILD_ID), target['channel_id']))
                self.bot.store.set(key, '1')

    async def repair(self, message, channel):
        """Return True when handled, False when unnecessary, None while blocked."""
        if channel.guild.id != CENTRAL_GUILD_ID or message.id > self.cutoff:
            return False
        channel_id, message_id = str(channel.id), str(message.id)
        row = self.db.execute('''SELECT * FROM banner_vote_order_repairs
            WHERE channel_id=? AND message_id=?''', (channel_id, message_id)).fetchone()
        if row is not None and row['phase'] == 'done':
            return True
        emojis = self.votes.emojis
        expected = [emoji.id for emoji in emojis]
        owned = [reaction for reaction in message.reactions if getattr(reaction.emoji, 'id', None) in expected]
        present = [reaction.emoji.id for reaction in owned]
        names = {emoji.id: emoji.name for emoji in emojis}
        if row is None:
            if present == expected[:len(present)] and all(
                    reaction.emoji.name == names[reaction.emoji.id] for reaction in owned):
                return False
            with self.db:
                self.db.execute('''INSERT INTO banner_vote_order_repairs(guild_id,channel_id,message_id)
                    VALUES(?,?,?)''', (str(CENTRAL_GUILD_ID), channel_id, message_id))
            phase, cleared, seeded = 'clear', 0, 0
        else:
            phase, cleared, seeded = row['phase'], row['cleared'], row['seeded']

        def save(phase, cleared, seeded):
            with self.db:
                self.db.execute('''UPDATE banner_vote_order_repairs SET phase=?,cleared=?,seeded=?
                    WHERE channel_id=? AND message_id=?''', (phase, cleared, seeded, channel_id, message_id))

        if phase == 'clear':
            for index, emoji in enumerate(emojis):
                bit = 1 << index
                if cleared & bit:
                    continue
                if emoji.id in present:
                    if not channel.permissions_for(channel.guild.me).manage_messages:
                        self.votes.status = ('Grant Manage Messages to reset old W/M/L votes in the community '
                                             'channel. New banner images remain enabled.')
                        return None
                    await message.clear_reaction(emoji)
                cleared |= bit
                save('clear', cleared, seeded)
            # Persist this transition before restoring any reaction. A retry must
            # never clear votes cast after the ordered reactions start returning.
            save('seed', cleared, seeded)
        for index, emoji in enumerate(emojis):
            bit = 1 << index
            if seeded & bit:
                continue
            await message.add_reaction(emoji)
            seeded |= bit
            save('seed', cleared, seeded)
        save('done', cleared, seeded)
        self.votes.status = 'W/M/L ready. Discord-confirmed names: win, mid, lose.'
        return True
