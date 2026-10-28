"""Official-community feedback: bounded storage and private, owner-scoped review."""

import hashlib

import discord

from community_hub import CENTRAL_GUILD_ID
from bot_views import BoundModal, reply
from bot_domain import safe
from global_views import ScopedView


class CommunityFeedback:
    def __init__(self, bot):
        self.bot,self.db = bot,bot.store.connection
        self.db.execute('''CREATE TABLE IF NOT EXISTS bot_feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,kind TEXT NOT NULL,
            body TEXT NOT NULL,fingerprint TEXT NOT NULL,created REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',version INTEGER NOT NULL DEFAULT 0)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS bot_feedback_pending ON bot_feedback(status,created)')
        self.db.commit()

    def require(self, i, *, owner=False):
        if i.guild_id != CENTRAL_GUILD_ID:
            raise ValueError('Feedback is available only in the official community.')
        self.bot.require_human(i)
        if owner:
            self.bot.require_owner(i)

    def cleanup(self):
        with self.db:
            self.db.execute('DELETE FROM bot_feedback WHERE created<?', (self.bot.store.clock()-30*86400,))
            self.db.execute('DELETE FROM bot_feedback WHERE id NOT IN (SELECT id FROM bot_feedback ORDER BY id DESC LIMIT 3000)')

    def submit(self, i, kind, body):
        self.require(i)
        body=body.strip()
        if kind not in {'bug','suggestion'} or not 10<=len(body)<=800:
            raise ValueError('Choose Bug or Suggestion and describe it in 10 to 800 characters.')
        self.cleanup()
        digest=hashlib.sha256((kind+':'+body).encode()).hexdigest()
        old=self.db.execute('SELECT id FROM bot_feedback WHERE user_id=? AND fingerprint=? AND created>?',
            (str(i.user.id),digest,self.bot.store.clock()-600)).fetchone()
        if old:
            return old[0]
        if not self.bot.globalchat.store.limit('feedback:'+str(i.user.id),3,600):
            raise ValueError('Please wait before sending more feedback.')
        with self.db:
            cursor=self.db.execute('INSERT INTO bot_feedback(user_id,kind,body,fingerprint,created) VALUES(?,?,?,?,?)',
                (str(i.user.id),kind,body,digest,self.bot.store.clock()))
        return cursor.lastrowid


class FeedbackForm(BoundModal):
    def __init__(self, bot, i):
        super().__init__(title='Community feedback')
        bot.feedback.require(i)
        self.bind(bot,i)
        self.kind=discord.ui.Select(options=[discord.SelectOption(label='Bug',value='bug'),discord.SelectOption(label='Suggestion',value='suggestion')])
        self.body=discord.ui.TextInput(style=discord.TextStyle.paragraph,min_length=10,max_length=800)
        self.add_item(discord.ui.Label(text='Category',component=self.kind))
        self.add_item(discord.ui.Label(text='Description',description='Read privately by the bot owner; retained for up to 30 days. Do not include secrets.',component=self.body))

    async def on_submit(self,i):
        if not await self.interaction_check(i):
            return
        ident=self.bot.feedback.submit(i,self.kind.values[0],str(self.body))
        await reply(i,f'**Feedback #{ident} received.** The bot owner can review it privately. Nothing was posted in a public channel.')


class FeedbackInbox(ScopedView):
    def __init__(self,bot,i):
        bot.feedback.require(i,owner=True)
        super().__init__(bot,i,owner=True)
        self.page=0
        self.selected=None
        self.version=0

    def description(self):
        self.bot.feedback.cleanup()
        rows=self.bot.store.rows("SELECT * FROM bot_feedback WHERE status='pending' ORDER BY id LIMIT 6 OFFSET ?",(self.page*5,))
        self.previous.disabled=self.page==0
        self.next.disabled=len(rows)<=5
        rows=rows[:5]
        self.choose.options=[discord.SelectOption(label=f'#{r["id"]} · {r["kind"]}',description=r['body'][:80],value=str(r['id'])) for r in rows] or [discord.SelectOption(label='No pending feedback',value='0')]
        self.choose.disabled=not rows
        selected=next((r for r in rows if r['id']==self.selected),rows[0] if rows else None)
        self.selected=selected['id'] if selected else None
        self.version=selected['version'] if selected else 0
        self.resolve.disabled=self.dismiss.disabled=not selected
        return ('## Official community feedback\nPrivate review · page '+str(self.page+1)
            +(f'\n\n**#{selected["id"]} · {selected["kind"]}**\n{safe(selected["body"],800)}\nSubmitted <t:{int(selected["created"])}:R>.' if selected else '\nNo pending feedback.'))

    async def refresh(self,i):
        from bot_ui import edit_response
        self.require(i)
        self.bot.feedback.require(i,owner=True)
        await edit_response(i,content=self.description(),view=self)

    @discord.ui.button(label='Previous',row=0)
    async def previous(self,i,button):
        self.page=max(0,self.page-1)
        await self.refresh(i)

    @discord.ui.button(label='Next',row=0)
    async def next(self,i,button):
        self.page+=1
        await self.refresh(i)

    @discord.ui.select(placeholder='Choose feedback',options=[discord.SelectOption(label='Loading',value='0')],row=1)
    async def choose(self,i,select):
        self.selected=int(select.values[0])
        await self.refresh(i)

    async def decide(self,i,status):
        self.require(i)
        self.bot.feedback.require(i,owner=True)
        with self.bot.store.connection:
            result=self.bot.store.connection.execute("UPDATE bot_feedback SET status=?,version=version+1 WHERE id=? AND version=? AND status='pending'",(status,self.selected,self.version))
        if result.rowcount!=1:
            raise ValueError('This feedback changed. Reopen the review before deciding.')
        await self.refresh(i)

    @discord.ui.button(label='Resolve',style=discord.ButtonStyle.success,row=2)
    async def resolve(self,i,button):
        await self.decide(i,'resolved')

    @discord.ui.button(label='Dismiss',row=2)
    async def dismiss(self,i,button):
        await self.decide(i,'dismissed')
