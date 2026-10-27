"""One-time, owner-authorized W/M/L reset in every configured banner channel."""

from datetime import datetime, timezone

import discord

class BannerVoteOrder:
    def __init__(self, votes):
        self.votes, self.bot, self.db = votes, votes.bot, votes.db
        self.cutoffs = {}
        self.db.execute('''CREATE TABLE IF NOT EXISTS banner_vote_order_repairs(
            guild_id TEXT NOT NULL, channel_id TEXT NOT NULL, message_id TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'clear', cleared INTEGER NOT NULL DEFAULT 0,
            seeded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(channel_id,message_id))''')
        self.db.commit()

    def prepare_scan(self):
        targets = self.db.execute('SELECT guild_id,channel_id FROM banner_targets').fetchall()
        active = {target['channel_id'] for target in targets}
        self.cutoffs = {channel_id: cutoff for channel_id, cutoff in self.cutoffs.items() if channel_id in active}
        for target in targets:
            channel_id = target['channel_id']
            if channel_id in self.cutoffs:
                continue
            key = 'banner-vote-order-scan:1:' + channel_id
            scanned = self.bot.store.get(key)
            cutoff_key = 'banner-vote-order-cutoff:1:' + channel_id
            cutoff = self.bot.store.get(cutoff_key)
            if cutoff is None:
                # Keep the previous release's boundary for channels already
                # scanned, while new channels get their own fixed boundary.
                cutoff = self.bot.store.get('banner-vote-order-cutoff:1') if scanned else None
                if cutoff is None:
                    cutoff = discord.utils.time_snowflake(
                        datetime.fromtimestamp(self.votes.relay.clock(), timezone.utc), high=True)
                self.bot.store.set(cutoff_key, cutoff)
            if not scanned:
                with self.db:
                    self.db.execute('''UPDATE banner_vote_backfill SET before_id=NULL,done=0,
                        scanned=0,rated=0,skipped=0,next_scan=0 WHERE guild_id=? AND channel_id=?''',
                        (target['guild_id'], channel_id))
                    self.bot.store.set(key, '1')
            self.cutoffs[channel_id] = int(cutoff)

    def description(self, channel):
        if not channel.permissions_for(channel.guild.me).manage_messages and self.db.execute(
                "SELECT 1 FROM banner_vote_order_repairs WHERE channel_id=? AND phase='clear' LIMIT 1",
                (str(channel.id),)).fetchone():
            return 'Grant Manage Messages to reset old W/M/L votes in this channel. New banner images remain enabled.'
        return None

    async def repair(self, message, channel):
        """Return True when handled, False when unnecessary, None while blocked."""
        target = self.votes.relay.target(channel.guild.id)
        if (not target or target['channel_id'] != str(channel.id)
                or message.id > self.cutoffs.get(str(channel.id), 0)):
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
                    VALUES(?,?,?)''', (str(channel.guild.id), channel_id, message_id))
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
