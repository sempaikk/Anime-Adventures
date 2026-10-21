"""Release trivia with native Discord screens and a single open-answer command."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import quiz_ui as screen
from quiz_content import QuestionDeck, load_pack
from scores import ScoreStore
from timing import PausableTimer

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
QUESTION_TIME = 45
COUNTDOWN_INTERVAL = 10
BETWEEN_QUESTIONS = 8
LOBBY_TIMEOUT = 120
PACK = load_pack()
log = logging.getLogger('adventures')
active_sessions: dict[int, QuizSession] = {}


class QuizSession:
    def __init__(self, channel, host, store, *, deck=None, clock=None):
        self.channel, self.host, self.store = channel, host, store
        self.pack = PACK
        self.group = 'all'
        self.question_time = QUESTION_TIME
        self.between_questions = BETWEEN_QUESTIONS
        self.deck = deck or QuestionDeck(self.selected_questions())
        self.clock = clock or time.monotonic
        self.running = False
        self.phase = 'lobby'
        self.current_question = None
        self.question_message = None
        self.question_number = 0
        self.had_participation = False
        self.timer = None
        self.answer_min_id = 0
        self.ends_at = None
        self.next_at = None
        self.answer_future = None
        self.runner = None
        self.ticker = None
        self.lobby_timer = None
        self.control_message = None
        self.control_view = None
        self.question_view = None
        self.stop_requested = False
        self.timing_changed = asyncio.Event()
        self.session_scores: dict[int, dict] = {}
        self.correct_count = 0
        self.last_result = None
        self.control_lock = asyncio.Lock()

    @property
    def deadline(self):
        return self.timer.deadline if self.timer else 0.0

    @property
    def is_paused(self):
        return bool(self.timer and self.timer.paused)

    @property
    def remaining_seconds(self):
        return self.timer.remaining if self.timer else self.question_time

    def timing_updated(self):
        # Every waiter observes its own generation, so no consumer can clear another's wakeup.
        previous = self.timing_changed
        self.timing_changed = asyncio.Event()
        previous.set()

    def pause(self):
        if self.phase not in ('question', 'intermission') or not self.timer:
            return False
        if self.phase == 'question' and (self.answer_future is None or self.answer_future.done()):
            return False
        if not self.timer.pause():
            return False
        self.phase = 'paused_question' if self.phase == 'question' else 'paused_intermission'
        self.timing_updated()
        return True

    def resume(self, interaction_id=0):
        if self.phase not in ('paused_question', 'paused_intermission') or not self.timer:
            return False
        question = self.phase == 'paused_question'
        if not self.timer.resume():
            return False
        self.phase = 'question' if question else 'intermission'
        if question:
            self.answer_min_id = max(self.answer_min_id, interaction_id)
            self.ends_at = datetime.now(timezone.utc) + timedelta(seconds=self.timer.remaining)
        else:
            self.next_at = datetime.now(timezone.utc) + timedelta(seconds=self.timer.remaining)
        self.timing_updated()
        return True

    async def await_answer(self):
        while self.running:
            event = self.timing_changed
            if self.answer_future.done():
                return await self.answer_future
            if not self.is_paused and self.remaining_seconds <= 0:
                self.answer_future.cancel()
                return None
            changed = asyncio.create_task(event.wait())
            try:
                await asyncio.wait(
                    (self.answer_future, changed),
                    timeout=None if self.is_paused else self.remaining_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                changed.cancel()
                await asyncio.gather(changed, return_exceptions=True)
        return None

    def selected_questions(self):
        categories = screen.GROUPS[self.group][1]
        return tuple(q for q in self.pack.questions if categories is None or q.category in categories)

    def release_channel(self):
        if active_sessions.get(self.channel.id) is self:
            del active_sessions[self.channel.id]

    async def open_lobby(self):
        self.running = True
        self.control_view = screen.lobby_panel(self, handle_control)
        self.control_message = await self.channel.send(view=self.control_view)
        self.lobby_timer = asyncio.create_task(self.expire_lobby(), name=f'lobby:{self.channel.id}')

    async def expire_lobby(self):
        await asyncio.sleep(LOBBY_TIMEOUT)
        if self.phase == 'lobby' and self.running:
            await self.stop_now('O painel fechou porque a partida não foi iniciada. Abra outra quando quiser.')

    def launch(self):
        self.running = True
        self.phase = 'starting'
        if self.lobby_timer:
            self.lobby_timer.cancel()
        self.runner = asyncio.create_task(self.run(), name=f'quiz:{self.channel.id}')

    async def retire_controls(self):
        async with self.control_lock:
            if self.control_view:
                self.control_view.retire()
                if self.control_message:
                    with contextlib.suppress(discord.HTTPException):
                        await self.control_message.edit(view=self.control_view)
                self.control_view = None
            self.control_message = None

    async def refresh_controls(self):
        async with self.control_lock:
            if not self.running or not self.control_message:
                return
            if self.phase == 'lobby':
                view = screen.lobby_panel(self, handle_control)
            elif self.phase in ('question', 'paused_question'):
                view = screen.question_panel(self, handle_control, self.remaining_seconds)
                self.question_view = view
            elif self.phase in ('paused_intermission', 'intermission') and self.last_result:
                winner, total = self.last_result
                view = screen.result_panel(self, winner, total, True, handle_control)
            else:
                return
            if self.control_view:
                self.control_view.stop()
            self.control_view = view
            await self.control_message.edit(view=view)

    def submit(self, message):
        """Claim synchronously so two correct messages cannot both win."""
        if (not self.running or self.phase != 'question' or self.question_message is None
                or self.answer_future is None or self.answer_future.done() or self.remaining_seconds <= 0):
            return False
        if message.author.bot or message.webhook_id is not None or message.id <= self.answer_min_id:
            return False
        self.had_participation = True
        if self.current_question.accepts(message.content):
            self.answer_future.set_result(message.author)
            return True
        return False

    async def update_clock(self, refresh_immediately=False):
        first = True
        while not self.answer_future.done():
            event = self.timing_changed
            if self.is_paused:
                await event.wait()
                first = True
                continue
            remaining = self.remaining_seconds
            if remaining <= 0:
                return
            if not (first and refresh_immediately):
                try:
                    await asyncio.wait_for(event.wait(), min(COUNTDOWN_INTERVAL, remaining))
                except asyncio.TimeoutError:
                    pass
            first = False
            if self.is_paused or self.answer_future.done():
                continue
            if self.remaining_seconds <= 0:
                return
            try:
                async with self.control_lock:
                    if self.is_paused or self.answer_future.done():
                        continue
                    self.question_view.clock_text.content = screen.clock_label(self, self.remaining_seconds)
                    await self.question_message.edit(view=self.question_view)
            except (discord.NotFound, discord.Forbidden):
                self.answer_future.cancel()
                return
            except discord.HTTPException:
                log.warning('Não foi possível atualizar o relógio no canal %s', self.channel.id)

    async def stop_ticker(self):
        if self.ticker:
            self.ticker.cancel()
            results = await asyncio.gather(self.ticker, return_exceptions=True)
            if isinstance(results[0], Exception):
                log.error('Falha no relógio do canal %s: %s', self.channel.id, type(results[0]).__name__)
            self.ticker = None

    async def play_question(self):
        await self.retire_controls()
        self.question_number += 1
        self.question_message = None
        self.had_participation = False
        self.current_question = self.deck.draw()
        self.answer_future = asyncio.get_running_loop().create_future()
        self.phase = 'question'
        publishing_started = self.clock()
        self.timer = PausableTimer(self.question_time, self.clock)
        self.ends_at = datetime.now(timezone.utc) + timedelta(seconds=self.question_time)
        self.question_view = screen.question_panel(self, handle_control, self.question_time)
        self.control_view = self.question_view
        self.question_message = await self.channel.send(view=self.question_view)
        self.control_message = self.question_message
        # Publishing latency must not consume a player's answer time.
        publish_lag = self.clock() - publishing_started
        self.timer = PausableTimer(self.question_time, self.clock)
        self.answer_min_id = self.question_message.id
        self.ends_at = datetime.now(timezone.utc) + timedelta(seconds=self.question_time)
        self.ticker = asyncio.create_task(self.update_clock(publish_lag >= 1), name=f'clock:{self.channel.id}')
        try:
            winner = await self.await_answer()
        finally:
            self.phase = 'resolving'
            await self.stop_ticker()
        total = None
        if winner:
            entry = self.session_scores.setdefault(winner.id, {'name': winner.display_name, 'points': 0, 'first': self.question_number})
            entry['name'] = winner.display_name
            entry['points'] += 1
            self.correct_count += 1
            try:
                total = self.store.award(str(self.question_message.id), winner.id, winner.display_name)
            except (OSError, sqlite3.Error):
                log.exception('Falha ao salvar pontuação da pergunta %s', self.question_message.id)
        async with self.control_lock:
            self.question_view.stop()
            with contextlib.suppress(discord.HTTPException):
                await self.question_message.edit(view=screen.closed_question_panel(self))
            self.control_message = None
            self.control_view = None
        continuing = self.had_participation and not self.stop_requested
        self.phase = 'intermission' if continuing else 'ended'
        self.timer = PausableTimer(self.between_questions, self.clock) if continuing else None
        self.next_at = datetime.now(timezone.utc) + timedelta(seconds=self.between_questions)
        self.last_result = (winner, total)
        self.control_view = screen.result_panel(self, winner, total, continuing, handle_control)
        publishing_started = self.clock()
        self.control_message = await self.channel.send(view=self.control_view)
        if continuing:
            # Give players the full reading interval after the result becomes visible.
            publish_lag = self.clock() - publishing_started
            self.timer = PausableTimer(self.between_questions, self.clock)
            self.next_at = datetime.now(timezone.utc) + timedelta(seconds=self.between_questions)
            if publish_lag >= 1:
                await self.refresh_controls()
        return continuing

    async def wait_between_questions(self):
        while self.running:
            event = self.timing_changed
            if not self.is_paused and self.remaining_seconds <= 0:
                return
            try:
                await asyncio.wait_for(event.wait(), None if self.is_paused else self.remaining_seconds)
            except asyncio.TimeoutError:
                return

    async def stop_now(self, reason):
        self.running = False
        self.phase = 'ended'
        current = asyncio.current_task()
        tasks = [task for task in (self.runner, self.lobby_timer) if task and task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.control_view:
            self.control_view.stop()
        self.release_channel()
        async with self.control_lock:
            if self.control_message:
                self.control_view = screen.ended_panel(self, reason, handle_control)
                with contextlib.suppress(discord.HTTPException):
                    await self.control_message.edit(view=self.control_view)
                # Persistent fallback handles replay and score buttons after cleanup.
                self.control_view.stop()

    async def run(self):
        try:
            while self.running:
                if not await self.play_question():
                    break
                await self.wait_between_questions()
        except asyncio.CancelledError:
            raise
        except discord.HTTPException:
            log.exception('Sessão interrompida por erro do Discord no canal %s', self.channel.id)
            with contextlib.suppress(discord.HTTPException):
                await self.channel.send('A aventura foi interrompida. Confira as permissões do canal e use **/adventures** para abrir outro painel.')
        except Exception:
            log.exception('Erro na sessão do canal %s', self.channel.id)
            with contextlib.suppress(discord.HTTPException):
                await self.channel.send('A aventura precisou ser encerrada. Use **/adventures** para começar outra.')
        finally:
            self.running = False
            self.phase = 'ended'
            if self.answer_future and not self.answer_future.done():
                self.answer_future.cancel()
            await self.stop_ticker()
            if self.control_view:
                self.control_view.stop()
            self.release_channel()


class AdventuresBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.scores = None

    async def setup_hook(self):
        data_dir = Path(os.getenv('DATA_DIR') or os.getenv('RAILWAY_VOLUME_MOUNT_PATH') or BASE_DIR)
        legacy = data_dir / 'scores.json'
        if not legacy.exists():
            legacy = BASE_DIR / 'scores.json'
        self.scores = ScoreStore(data_dir / 'scores.sqlite3', legacy)
        self.add_view(screen.PersistentControls(handle_control))
        synced = await self.tree.sync()
        log.info('%s comando(s) sincronizado(s); %s perguntas Release; interface Components V2', len(synced), len(PACK.questions))

    async def close(self):
        sessions = list(active_sessions.values())
        tasks = []
        for session in sessions:
            session.running = False
            if session.control_view:
                session.control_view.retire()
            for task in (session.runner, session.lobby_timer):
                if task:
                    task.cancel()
                    tasks.append(task)
            session.release_channel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.scores:
            self.scores.close()
            self.scores = None
        await super().close()


bot = AdventuresBot()


def permission_problem(interaction):
    if interaction.guild is None or interaction.channel is None or not hasattr(interaction.channel, 'send'):
        return 'Use este comando em um canal de texto do servidor.'
    permissions = interaction.app_permissions
    can_send = permissions.send_messages_in_threads if isinstance(interaction.channel, discord.Thread) else permissions.send_messages
    if not (permissions.view_channel and can_send and permissions.embed_links):
        return 'Preciso de **Ver canal**, **Enviar mensagens** e **Inserir links** para apresentar o quiz aqui.'
    return None


async def begin_lobby(interaction):
    problem = permission_problem(interaction)
    if problem:
        await interaction.response.send_message(problem, ephemeral=True)
        return
    existing = active_sessions.get(interaction.channel.id)
    if existing and existing.running:
        await interaction.response.send_message('Já existe uma aventura neste canal. Use o painel mais recente para participar.', ephemeral=True)
        return
    session = QuizSession(interaction.channel, interaction.user, bot.scores)
    session.running = True
    active_sessions[session.channel.id] = session
    try:
        await interaction.response.send_message('✦ Painel aberto! Escolha os assuntos e toque em **Começar aventura**.', ephemeral=True)
        await session.open_lobby()
    except BaseException:
        session.running = False
        if session.control_view:
            session.control_view.stop()
        session.release_channel()
        raise


def is_moderator(user):
    permissions = getattr(user, 'guild_permissions', None)
    return bool(permissions and any(getattr(permissions, name, False) for name in ('administrator', 'manage_guild', 'manage_channels')))


async def handle_control(interaction, action, value=None):
    session = active_sessions.get(interaction.channel_id)
    if action == 'help':
        await interaction.response.send_message(view=screen.help_panel(), ephemeral=True)
        return
    if action == 'scores':
        total = None
        try:
            if bot.scores:
                total = bot.scores.points(interaction.user.id)
        except sqlite3.Error:
            log.exception('Falha ao consultar pontos')
        await interaction.response.send_message(view=screen.score_panel(session, interaction.user, total), ephemeral=True)
        return
    if action == 'replay':
        await begin_lobby(interaction)
        return
    if (session is None or not session.running or session.control_message is None
            or interaction.message is None or session.control_message.id != interaction.message.id):
        await interaction.response.send_message('Este painel já foi concluído. Use o painel mais recente ou **/adventures** para começar.', ephemeral=True)
        return
    owner = interaction.user.id == session.host.id
    if action in ('start', 'category', 'time'):
        if not owner:
            await interaction.response.send_message('O anfitrião escolhe as opções e inicia a partida. Você pode responder assim que ela começar!', ephemeral=True)
            return
        if session.phase != 'lobby':
            await interaction.response.send_message('As opções são escolhidas antes de começar a aventura.', ephemeral=True)
            return
        if action == 'category':
            if value not in screen.GROUPS:
                await interaction.response.send_message('Escolha uma das categorias do menu.', ephemeral=True)
                return
            session.group = value
        elif action == 'time':
            if value not in ('30', '45', '60'):
                await interaction.response.send_message('Escolha 30, 45 ou 60 segundos no menu.', ephemeral=True)
                return
            session.question_time = int(value)
        else:
            session.deck = QuestionDeck(session.selected_questions())
            session.launch()  # Claims starting state before the first await.
        await interaction.response.defer()
        if action != 'start':
            await session.refresh_controls()
        return
    if not (owner or is_moderator(interaction.user)):
        await interaction.response.send_message('Pausar, retomar e encerrar ficam com o anfitrião e a moderação. Todos podem consultar o placar e jogar.', ephemeral=True)
        return
    if action == 'pause':
        if session.is_paused:
            # A repeated click can recover a panel whose previous edit failed.
            try:
                await interaction.response.defer()
            finally:
                await session.refresh_controls()
            return
        if not session.pause():
            await interaction.response.send_message('Esta etapa já terminou ou está em pausa. Use os controles do painel mais recente.', ephemeral=True)
            return
        try:
            await interaction.response.defer()
        finally:
            await session.refresh_controls()
    elif action == 'resume':
        if not session.resume(getattr(interaction, 'id', 0)):
            if session.phase in ('question', 'intermission'):
                try:
                    await interaction.response.defer()
                finally:
                    await session.refresh_controls()
                return
            await interaction.response.send_message('Esta etapa já foi retomada ou encerrada.', ephemeral=True)
            return
        try:
            await interaction.response.defer()
        finally:
            await session.refresh_controls()
    elif action == 'stop':
        if session.phase in ('question', 'resolving'):
            session.stop_requested = True
            await interaction.response.send_message('Esta será a última pergunta. O tempo e o ponto em disputa continuam valendo até ela terminar.', ephemeral=True)
            await session.refresh_controls()
        else:
            # Mark the session stopped before acknowledging; the loop cannot start another round.
            session.running = False
            try:
                await interaction.response.defer()
            finally:
                await session.stop_now('Encerrada pelo anfitrião ou pela moderação. Obrigado por jogar!')
    else:
        await interaction.response.send_message('A partida mudou de etapa. Use os controles do painel mais recente.', ephemeral=True)


@bot.event
async def on_ready():
    log.info('Conectado como %s; %s sessões ativas', bot.user, len(active_sessions))


@bot.event
async def on_message(message: discord.Message):
    if not message.author.bot:
        session = active_sessions.get(message.channel.id)
        if session:
            session.submit(message)


async def release_deleted_panel(channel_id, message_ids):
    session = active_sessions.get(channel_id)
    if not session or not session.control_message or session.control_message.id not in message_ids:
        return
    # A winner claimed just before deletion must still receive the earned point.
    future = session.answer_future
    if session.phase in ('question', 'resolving') and future and future.done() and not future.cancelled():
        session.stop_requested = True
        return
    await session.stop_now('O painel da partida foi removido. Use /adventures para abrir outra aventura.')


@bot.event
async def on_raw_message_delete(payload):
    await release_deleted_panel(payload.channel_id, {payload.message_id})


@bot.event
async def on_raw_bulk_message_delete(payload):
    await release_deleted_panel(payload.channel_id, payload.message_ids)


@bot.event
async def on_guild_channel_delete(channel):
    session = active_sessions.get(channel.id)
    if session:
        future = session.answer_future
        if session.phase in ('question', 'resolving') and future and future.done() and not future.cancelled():
            session.stop_requested = True
            return
        await session.stop_now('O canal da partida foi removido.')


@bot.tree.command(name='adventures', description='Abra o quiz Release de Anime Adventures com imagens, placar e pausa.')
@app_commands.guild_only()
async def adventures(interaction: discord.Interaction):
    await begin_lobby(interaction)


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('DISCORD_TOKEN não foi encontrado nas variáveis de ambiente.')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    bot.run(token)
