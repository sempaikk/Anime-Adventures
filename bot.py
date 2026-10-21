"""Game trivia with native Discord screens, chat and three-choice rounds."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import signal
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import quiz_ui as screen
import adventure_views as extra_screen
from quiz_content import QuestionDeck, load_pack, normalize_answer
from quiz_guard import Cooldowns
from interaction_errors import respond_to_error
from scores import ScoreStore
from storage_maintenance import maintain_storage
from timing import PausableTimer
from difficulty import LABELS, FORMATS, matches
from adventure_repository import AdventureRepository
from adventure_state import AdventureState
from runtime_health import RuntimeHealth

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
QUESTION_TIME = 45
COUNTDOWN_INTERVAL = 10
BETWEEN_QUESTIONS = 8
LOBBY_TIMEOUT = 120
PAUSE_TIMEOUT = 600
CHAT_ATTEMPTS = 3
MAX_ANSWER_LENGTH = 160
MAX_SESSIONS = 50
MAX_GUILD_SESSIONS = 3
SHUTDOWN_PANEL_TIMEOUT = 3
PACK = load_pack()
log = logging.getLogger('adventures')
active_sessions: dict[int, QuizSession] = {}
click_limits = Cooldowns()


class QuizSession(AdventureState):
    def __init__(self, channel, host, store, *, deck=None, clock=None):
        self.channel, self.host, self.store = channel, host, store
        self.guild_id = getattr(getattr(channel, 'guild', None), 'id', None)
        self.pack = PACK
        self.group = 'all'
        self.round_limit = 10
        self.question_time = QUESTION_TIME
        self.between_questions = BETWEEN_QUESTIONS
        self.init_adventure(getattr(bot, 'adventures', None))
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
        self.choice_order = []
        self.choice_attempts = set()
        self.chat_attempts = {}
        self.chat_attempt_limit = CHAT_ATTEMPTS
        self.pause_timeout = PAUSE_TIMEOUT
        self.pause_expiry = None
        self.rendered_state = None
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
        self.global_credited = None
        self.winner_recorded = False
        self.award_total = None
        self.control_lock = asyncio.Lock()
        self.connection_paused = False

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
        self.pause_expiry = asyncio.create_task(self.expire_pause(), name=f'pause:{self.channel.id}')
        self.timing_updated()
        return True

    def cancel_pause_expiry(self):
        task, self.pause_expiry = self.pause_expiry, None
        if task and task is not asyncio.current_task():
            task.cancel()

    async def expire_pause(self):
        await asyncio.sleep(self.pause_timeout)
        if self.running and self.is_paused:
            self.pause_expiry = None  # The runner can finish without cancelling this task.
            minutes = max(1, round(self.pause_timeout / 60))
            await self.stop_now(f'A pausa chegou a {minutes} minutos. Abra outra partida quando quiser jogar.')

    def resume(self, interaction_id=0):
        if self.phase not in ('paused_question', 'paused_intermission') or not self.timer:
            return False
        question = self.phase == 'paused_question'
        if not self.timer.resume():
            return False
        self.phase = 'question' if question else 'intermission'
        self.connection_paused = False
        self.cancel_pause_expiry()
        if question:
            self.answer_min_id = max(self.answer_min_id, interaction_id)
            self.ends_at = datetime.now(timezone.utc) + timedelta(seconds=self.timer.remaining)
        else:
            self.next_at = datetime.now(timezone.utc) + timedelta(seconds=self.timer.remaining)
        self.timing_updated()
        return True

    def pause_for_connection(self):
        # Publication resets its timer after send(); pause it only once visible.
        if self.control_message is not None and self.pause():
            self.connection_paused = True
            return True
        return False

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
        return tuple(q for q in self.pack.questions if (categories is None or q.category in categories)
                     and matches(q,self.difficulty,self.answer_mode))

    def release_channel(self):
        if active_sessions.get(self.channel.id) is self:
            del active_sessions[self.channel.id]

    async def open_lobby(self):
        self.running = True
        self.control_view = screen.lobby_panel(self, handle_control)
        self.control_message = await self.channel.send(view=self.control_view)
        self.rendered_state = self.control_state()
        self.remember_panel()
        self.lobby_timer = asyncio.create_task(self.expire_lobby(), name=f'lobby:{self.channel.id}')

    async def expire_lobby(self):
        await asyncio.sleep(LOBBY_TIMEOUT)
        if self.phase == 'lobby' and self.running:
            await self.stop_now('Ninguém iniciou a partida. Use /adventures quando quiser jogar.')

    def launch(self):
        self.running = True
        self.phase = 'starting'
        self.checkpoint()
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

    def control_state(self):
        return (getattr(self.control_message, 'id', None), self.phase, self.group,
                self.question_time, self.round_limit, self.stop_requested, self.question_number, self.ends_at, self.next_at,
                self.difficulty,self.answer_mode,self.lobby_page,self.host.id,self.host_missing)

    def finish_reason(self):
        if self.stop_requested:
            return 'Partida encerrada pelo anfitrião ou pela moderação.'
        if self.round_limit and self.question_number >= self.round_limit:
            return f'As {self.round_limit} perguntas foram concluídas. Valeu por jogar!'
        return 'Ninguém tentou responder essa rodada. Quer jogar de novo?'

    async def refresh_controls(self):
        async with self.control_lock:
            if not self.running or not self.control_message:
                return
            state = self.control_state()
            if state == self.rendered_state:
                return
            if self.phase == 'lobby':
                view = screen.lobby_panel(self, handle_control)
            elif self.phase == 'recovery':
                view = extra_screen.recovery_panel(self,handle_control)
            elif self.phase in ('question', 'paused_question'):
                view = screen.question_panel(self, handle_control, self.remaining_seconds)
            elif self.phase in ('paused_intermission', 'intermission') and self.last_result:
                winner, total = self.last_result
                view = screen.result_panel(self, winner, total, True, handle_control)
            else:
                return
            await self.control_message.edit(view=view)
            if self.control_view:
                self.control_view.stop()
            self.control_view = view
            if self.phase in ('question', 'paused_question'):
                self.question_view = view
            self.rendered_state = state
            self.checkpoint()

    def submit(self, message):
        """Claim synchronously so two correct messages cannot both win."""
        if (not self.running or self.phase != 'question' or self.question_message is None
                or self.answer_future is None or self.answer_future.done() or self.remaining_seconds <= 0):
            return False
        if self.current_question.options:
            return False
        if message.author.bot or message.webhook_id is not None or message.id <= self.answer_min_id:
            return False
        if len(message.content) > MAX_ANSWER_LENGTH:
            return False
        answer = normalize_answer(message.content)
        if not answer:
            return False
        attempts = self.chat_attempts.get(message.author.id, set())
        if answer in attempts or len(attempts) >= self.chat_attempt_limit:
            return False
        if not self.track_attempt(message.author):
            return False
        attempts.add(answer)
        self.chat_attempts[message.author.id] = attempts
        self.had_participation = True
        if answer in self.current_question.accepted:
            self.answer_future.set_result(message.author)
            self.record_winner(message.author)
            return True
        return False

    def submit_choice(self, user, index, interaction_id):
        """Validate and claim before awaiting Discord; one attempt per human per round."""
        if self.is_paused:
            return 'paused'
        if (not self.running or self.phase != 'question' or self.question_message is None or not self.current_question.options
                or self.answer_future is None or self.answer_future.done() or self.remaining_seconds <= 0):
            return 'closed'
        if interaction_id <= self.answer_min_id:
            return 'stale'
        if getattr(user, 'bot', False) or not 0 <= index < len(self.choice_order):
            return 'invalid'
        if user.id in self.choice_attempts:
            return 'duplicate'
        if not self.track_attempt(user):
            return 'full'
        self.choice_attempts.add(user.id)
        self.had_participation = True
        if self.current_question.accepts(self.choice_order[index]):
            self.answer_future.set_result(user)
            self.record_winner(user)
            return 'correct'
        return 'wrong'

    def record_winner(self, winner):
        """Record a winner synchronously before UI acknowledgement or task cancellation."""
        if self.winner_recorded:
            return self.award_total
        self.winner_recorded = True
        self.round_winner_id = winner.id
        if winner.id not in self.round_people:
            self.track_attempt(winner)
        entry = self.session_scores.setdefault(winner.id, {'name': winner.display_name, 'points': 0, 'first': self.question_number})
        entry['name'] = winner.display_name
        entry['points'] += 1
        self.correct_count += 1
        try:
            credit = self.store.credit(str(self.question_message.id), winner.id, winner.display_name,
                                       content_id=f'{self.pack.stage}:{self.current_question.id}')
            self.award_total, self.global_credited = credit.total, credit.credited
        except (OSError, sqlite3.Error, ValueError):
            log.exception('Falha ao salvar pontuação da pergunta %s', self.question_message.id)
        self.checkpoint()
        return self.award_total

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
        await check_host_presence(self)
        await self.retire_controls()
        self.question_number += 1
        self.question_message = None
        self.had_participation = False
        self.current_question = self.deck.draw()
        self.choice_order = list(self.current_question.options)
        random.SystemRandom().shuffle(self.choice_order)
        self.choice_attempts.clear()
        self.chat_attempts.clear()
        self.global_credited = None
        self.winner_recorded = False
        self.award_total = None
        self.round_people = {}
        self.round_winner_id = None
        self.round_complete = self.round_reviewed = False
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
        if bot.connection_lost:
            self.pause_for_connection()
        self.remember_panel()
        try:
            winner = await self.await_answer()
        finally:
            self.phase = 'resolving'
            await self.stop_ticker()
        total = self.record_winner(winner) if winner else None
        self.finish_round_review(winner.id if winner else None)
        self.checkpoint()
        async with self.control_lock:
            self.question_view.stop()
            with contextlib.suppress(discord.HTTPException):
                await self.question_message.edit(view=screen.closed_question_panel(self))
            self.control_message = None
            self.control_view = None
        continuing = (self.had_participation and not self.stop_requested
                      and (self.round_limit is None or self.question_number < self.round_limit))
        self.phase = 'intermission' if continuing else 'ended'
        self.timer = PausableTimer(self.between_questions, self.clock) if continuing else None
        self.next_at = datetime.now(timezone.utc) + timedelta(seconds=self.between_questions)
        self.last_result = (winner, total)
        self.control_view = screen.result_panel(self, winner, total, continuing, handle_control)
        publishing_started = self.clock()
        self.control_message = await self.channel.send(view=self.control_view)
        self.remember_panel(resolved=True)
        if continuing:
            # Give players the full reading interval after the result becomes visible.
            publish_lag = self.clock() - publishing_started
            self.timer = PausableTimer(self.between_questions, self.clock)
            self.next_at = datetime.now(timezone.utc) + timedelta(seconds=self.between_questions)
            if bot.connection_lost:
                self.pause_for_connection()
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
        self.cancel_pause_expiry()
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
            self.remember_panel(resolved=self.round_complete)
        self.checkpoint('finished')

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
                await self.channel.send('Não deu para continuar a partida. Confira as permissões do canal e use **/adventures** para tentar de novo.')
        except Exception:
            log.exception('Erro na sessão do canal %s', self.channel.id)
            with contextlib.suppress(discord.HTTPException):
                await self.channel.send('Deu um erro e a partida precisou parar. Use **/adventures** para jogar de novo.')
        finally:
            self.running = False
            self.phase = 'ended'
            self.cancel_pause_expiry()
            if self.answer_future and not self.answer_future.done():
                self.answer_future.cancel()
            await self.stop_ticker()
            if self.control_view:
                self.control_view.stop()
            self.release_channel()
            if not self.suspending:
                self.checkpoint('finished')


class AdventuresBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.scores = None
        self.storage_task = None
        self.connection_lost = False
        self.shutdown_task = None
        self.close_guard = asyncio.Lock()
        self.adventures = None
        self.session_task = None
        self.host_task = None
        self.restored_sessions = False
        self.shutting_down = False
        self.health = RuntimeHealth(lambda: self.is_ready() and not self.connection_lost and not self.shutting_down,
                                    lambda: self.scores.connection if self.scores else None)
        self.pack = PACK

    async def setup_hook(self):
        data_dir = Path(os.getenv('DATA_DIR') or os.getenv('RAILWAY_VOLUME_MOUNT_PATH') or BASE_DIR)
        legacy = data_dir / 'scores.json'
        if not legacy.exists():
            legacy = BASE_DIR / 'scores.json'
        self.scores = ScoreStore(data_dir / 'scores.sqlite3', legacy)
        self.adventures = AdventureRepository(self.scores.connection)
        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, self.request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            log.info('Encerramento por sinal não disponível nesta plataforma.')
        log.info('Banco de pontos: %s', data_dir / 'scores.sqlite3')
        self.storage_task = asyncio.create_task(self.monitor_storage(), name='storage-maintenance')
        self.session_task = asyncio.create_task(self.monitor_sessions(),name='match-checkpoints')
        self.host_task = asyncio.create_task(self.monitor_hosts(),name='host-presence')
        self.add_view(screen.PersistentControls(handle_control))
        self.add_view(extra_screen.PersistentExtras(handle_control))
        extra_screen.DynamicControls.dispatch = handle_control
        extra_screen.DynamicTransfer.dispatch = handle_control
        self.add_dynamic_items(extra_screen.DynamicControls,extra_screen.DynamicTransfer)
        await self.health.start(int(os.getenv('PORT','8080')))
        synced = await self.tree.sync()
        log.info('%s comando(s) sincronizado(s); %s perguntas Release; interface Components V2', len(synced), len(PACK.questions))

    async def monitor_storage(self):
        while self.scores is not None:
            try:
                report = await asyncio.to_thread(maintain_storage, self.scores.path)
                self.health.update_storage(report)
                if self.adventures:
                    self.adventures.cleanup()
                log.info('Armazenamento: banco=%s bytes, livre=%s bytes, backup=%s (%s bytes)',
                         report['database_bytes'], report['free_bytes'], report['backup'], report['backup_bytes'])
            except (OSError, sqlite3.Error, TimeoutError):
                with contextlib.suppress(OSError):
                    usage = await asyncio.to_thread(shutil.disk_usage,self.scores.path.parent)
                    self.health.update_storage({'backup':'failed','free_bytes':usage.free,'total_bytes':usage.total})
                self.health.backup_error = True
                log.exception('A cópia local dos pontos não pôde ser atualizada; banco e cópia anterior preservados.')
            await asyncio.sleep(3600)

    async def monitor_sessions(self):
        while True:
            await asyncio.sleep(5)
            for session in list(active_sessions.values()):
                if session.running and session.dirty:
                    session.checkpoint()

    async def monitor_hosts(self):
        async def check(session):
            missing = session.host_missing
            await check_host_presence(session)
            if session.running and missing != session.host_missing:
                await session.refresh_controls()
        while True:
            await asyncio.sleep(15)
            results = await asyncio.gather(*(check(s) for s in list(active_sessions.values()) if s.running),return_exceptions=True)
            if any(isinstance(result,Exception) for result in results):
                log.warning('Alguns controles de anfitrião não puderam ser atualizados.')

    def request_shutdown(self):
        if self.shutdown_task is None:
            self.shutdown_task = asyncio.create_task(self.close(), name='graceful-shutdown')

    async def close(self):
        async with self.close_guard:
            await self.close_resources()

    async def close_resources(self):
        self.shutting_down = True
        if self.host_task:
            self.host_task.cancel()
            await asyncio.gather(self.host_task,return_exceptions=True)
            self.host_task = None
        if self.session_task:
            self.session_task.cancel()
            await asyncio.gather(self.session_task,return_exceptions=True)
            self.session_task = None
        if self.storage_task:
            self.storage_task.cancel()
            await asyncio.gather(self.storage_task, return_exceptions=True)
            self.storage_task = None
        sessions = list(active_sessions.values())
        tasks = []
        for session in sessions:
            if (session.repository is not None and session.running and session.phase!='ended'
                    and not session.stop_requested):
                session.suspending = True
                session.checkpoint('suspended')
            elif session.repository is not None:
                if session.winner_recorded and not session.round_reviewed:
                    session.finish_round_review(session.round_winner_id)
                session.checkpoint('finished')
            session.running = False
            session.cancel_pause_expiry()
            if session.control_view:
                session.control_view.retire()
            for task in (session.runner, session.lobby_timer):
                if task:
                    task.cancel()
                    tasks.append(task)
            session.release_channel()
        await asyncio.gather(*tasks, return_exceptions=True)

        async def finish_panel(session):
            if session.control_message:
                view = (extra_screen.recovery_panel(session,handle_control,restarting=True) if session.suspending else
                        screen.ended_panel(session, 'O bot está reiniciando. Seus pontos salvos continuam no total. Use /adventures quando ele voltar.', handle_control))
                try:
                    with contextlib.suppress(discord.HTTPException):
                        await session.control_message.edit(view=view)
                finally:
                    view.stop()
        try:
            async with asyncio.timeout(SHUTDOWN_PANEL_TIMEOUT):
                await asyncio.gather(*(finish_panel(session) for session in sessions))
        except TimeoutError:
            log.warning('Alguns painéis não puderam receber o aviso de reinício a tempo.')
        await self.health.close()
        if self.scores:
            self.scores.close()
            self.scores = None
        self.adventures = None
        await super().close()


bot = AdventuresBot()


def permission_problem(interaction):
    if interaction.guild is None or interaction.channel is None or not hasattr(interaction.channel, 'send'):
        return 'Use este comando em um canal de texto do servidor.'
    permissions = interaction.app_permissions
    can_send = permissions.send_messages_in_threads if isinstance(interaction.channel, discord.Thread) else permissions.send_messages
    if not (permissions.view_channel and can_send and permissions.embed_links):
        return 'Preciso de **Ver canal**, **Enviar mensagens** e **Inserir links** para apresentar a partida aqui.'
    return None


async def begin_lobby(interaction):
    problem = permission_problem(interaction)
    if problem:
        await interaction.response.send_message(problem, ephemeral=True)
        return
    if bot.shutting_down:
        await interaction.response.send_message('O bot está reiniciando. Tente abrir a partida quando ele voltar.',ephemeral=True)
        return
    existing = active_sessions.get(interaction.channel.id)
    if existing and existing.running:
        await interaction.response.send_message('Já tem uma partida aberta neste canal. É só participar pelo painel mais recente.', ephemeral=True)
        return
    if bot.adventures:
        saved = bot.adventures.open_channel(interaction.channel.id)
        if saved:
            await interaction.response.defer(ephemeral=True)
            recovered = await restore_one_session(interaction.channel,saved)
            await interaction.followup.send('Encontrei uma partida salva. Use o painel de recuperação neste canal.' if recovered else
                'Não consegui retomar a partida salva agora. Seus pontos foram preservados. Tente /adventures novamente.',ephemeral=True)
            return
    if bot.connection_lost:
        await interaction.response.send_message('A conexão com o Discord está voltando. Espere um momento para abrir a partida.', ephemeral=True)
        return
    running = [s for s in active_sessions.values() if s.running]
    guild_id = getattr(interaction.guild, 'id', None)
    if len(running) >= MAX_SESSIONS:
        await interaction.response.send_message('Já tem bastante partida rolando agora. Tente novamente quando uma delas terminar.', ephemeral=True)
        return
    if guild_id is not None and sum(s.guild_id == guild_id for s in running) >= MAX_GUILD_SESSIONS:
        await interaction.response.send_message(f'Este servidor já tem {MAX_GUILD_SESSIONS} partidas abertas. Entre em uma delas ou espere uma terminar.', ephemeral=True)
        return
    if not click_limits.allow(('lobby', interaction.user.id), 3):
        await interaction.response.send_message('Espere 3 segundos antes de abrir outra partida.', ephemeral=True)
        return
    session = QuizSession(interaction.channel, interaction.user, bot.scores)
    session.guild_id = guild_id
    session.running = True
    active_sessions[session.channel.id] = session
    try:
        await interaction.response.send_message('Painel aberto! Escolha as opções e toque em **Começar**.', ephemeral=True)
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
    root_action = action.split(':',1)[0]
    if root_action in ('review','review_page','report','reports','report_page','report_done','status','manage') and not click_limits.allow(('extra',root_action,interaction.user.id),.75):
        await interaction.response.defer()
        return
    from adventure_controls import handle_feature
    if await handle_feature(interaction,action,value,session=session,client=bot,callback=handle_control,is_moderator=is_moderator):
        return
    if action in ('help', 'scores') and not click_limits.allow(('private', action, interaction.user.id), .75):
        await interaction.response.defer()
        return
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
        await interaction.response.send_message('Esse painel já foi encerrado. Use o mais recente ou abra outro com **/adventures**.', ephemeral=True)
        return
    if action.startswith('answer:'):
        try:
            index = int(action.split(':', 1)[1])
        except ValueError:
            index = -1
        result = session.submit_choice(interaction.user, index, interaction.id)
        responses = {
            'correct': 'Acertou e chegou primeiro! +1 ponto nesta partida.',
            'wrong': 'Não foi dessa vez! Sua escolha já contou. A resposta aparece no fim da rodada.',
            'duplicate': 'Você já escolheu nesta rodada. Cada pessoa tem uma tentativa por pergunta com alternativas.',
            'paused': 'A partida está pausada. Espere retomar para escolher.',
            'stale': 'Esse clique é de antes da retomada. Escolha de novo no painel atual.',
            'closed': 'Essa rodada já fechou ou o ponto já foi marcado. Espere a próxima!',
            'invalid': 'Essa alternativa não está disponível. Use os botões da pergunta atual.',
            'full': 'Esta partida atingiu o limite de 200 participantes.',
        }
        await interaction.response.send_message(responses[result], ephemeral=True)
        return
    owner = interaction.user.id == session.host.id
    if action in ('start', 'category', 'time', 'rounds','difficulty','format','advanced'):
        if not owner:
            await interaction.response.send_message('Só o anfitrião atual pode ajustar as opções e começar. Quando a pergunta aparecer, todo mundo pode responder!', ephemeral=True)
            return
        if session.phase != 'lobby':
            await interaction.response.send_message('Essas opções só podem mudar antes da partida começar.', ephemeral=True)
            return
        if action == 'advanced':
            session.lobby_page = 'main' if session.lobby_page == 'advanced' else 'advanced'
        elif action == 'difficulty':
            if value not in LABELS:
                await interaction.response.send_message('Escolha um nível de dificuldade do menu.',ephemeral=True)
                return
            session.difficulty = value
        elif action == 'format':
            if value not in FORMATS:
                await interaction.response.send_message('Escolha um formato do menu.',ephemeral=True)
                return
            session.answer_mode = value
        elif action == 'category':
            if value not in screen.GROUPS:
                await interaction.response.send_message('Escolha uma das categorias do menu.', ephemeral=True)
                return
            session.group = value
        elif action == 'time':
            if value not in ('30', '45', '60'):
                await interaction.response.send_message('Escolha 30, 45 ou 60 segundos no menu.', ephemeral=True)
                return
            session.question_time = int(value)
        elif action == 'rounds':
            if value not in ('10', '20', '30', 'continuous'):
                await interaction.response.send_message('Escolha 10, 20, 30 perguntas ou uma partida contínua.', ephemeral=True)
                return
            session.round_limit = None if value == 'continuous' else int(value)
        else:
            if not session.selected_questions():
                await interaction.response.send_message('Essa combinação não tem perguntas. Ajuste o assunto, nível ou formato.',ephemeral=True)
                return
            session.deck = QuestionDeck(session.selected_questions())
            session.launch()  # Claims starting state before the first await.
        await interaction.response.defer()
        if action != 'start':
            await session.refresh_controls()
        return
    if not (owner or is_moderator(interaction.user)):
        await interaction.response.send_message('Só o anfitrião atual e a moderação podem pausar, retomar ou encerrar. Você pode responder e consultar o placar normalmente.', ephemeral=True)
        return
    if action == 'pause':
        if session.is_paused:
            session.connection_paused = False  # Keep an explicit manual pause after reconnect.
            # A repeated click can recover a panel whose previous edit failed.
            try:
                await interaction.response.defer()
            finally:
                await session.refresh_controls()
            return
        if not session.pause():
            await interaction.response.send_message('Essa rodada já terminou ou está pausada. Use o painel mais recente.', ephemeral=True)
            return
        try:
            await interaction.response.defer()
        finally:
            await session.refresh_controls()
    elif action == 'resume':
        if bot.connection_lost:
            await interaction.response.send_message('A conexão com o Discord ainda está voltando. O tempo continua pausado.', ephemeral=True)
            return
        if not session.resume(getattr(interaction, 'id', 0)):
            if session.phase in ('question', 'intermission'):
                try:
                    await interaction.response.defer()
                finally:
                    await session.refresh_controls()
                return
            await interaction.response.send_message('Essa rodada já voltou ou foi encerrada. Confira o painel mais recente.', ephemeral=True)
            return
        try:
            await interaction.response.defer()
        finally:
            await session.refresh_controls()
    elif action == 'stop':
        if session.phase in ('question', 'resolving'):
            session.stop_requested = True
            await interaction.response.send_message('Beleza, essa é a última pergunta! Ainda dá para responder e ganhar o ponto antes de encerrar.', ephemeral=True)
            await session.refresh_controls()
        else:
            # Mark the session stopped before acknowledging; the loop cannot start another round.
            session.running = False
            try:
                await interaction.response.defer()
            finally:
                await session.stop_now('Partida encerrada pelo anfitrião ou pela moderação. Valeu por jogar!')
    else:
        await interaction.response.send_message('A partida já passou para outra rodada. Use o painel mais recente.', ephemeral=True)


@bot.event
async def on_ready():
    await restore_connection()
    if not bot.restored_sessions and bot.adventures:
        bot.restored_sessions = True
        await restore_saved_sessions()
    log.info('Conectado como %s; %s sessões ativas', bot.user, len(active_sessions))


@bot.event
async def on_disconnect():
    bot.connection_lost = True
    paused = sum(session.pause_for_connection() for session in list(active_sessions.values()) if session.running)
    log.warning('Conexão com o Discord interrompida; %s relógio(s) pausado(s).', paused)


async def restore_connection():
    bot.connection_lost = False
    minimum_id = discord.utils.time_snowflake(datetime.now(timezone.utc), high=True)
    resumed = []
    for session in list(active_sessions.values()):
        if session.connection_paused:
            session.connection_paused = False
            if session.running and session.resume(minimum_id):
                resumed.append(session)
    results = await asyncio.gather(*(session.refresh_controls() for session in resumed), return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            log.warning('O painel não pôde ser atualizado após reconectar: %s', type(result).__name__)


@bot.event
async def on_resumed():
    await restore_connection()


async def check_host_presence(session):
    guild = getattr(session.channel,'guild',None)
    if guild is None or not hasattr(guild,'fetch_member'):
        return
    last = getattr(session,'last_host_check',0)
    if time.monotonic() - last < 60:
        return
    session.last_host_check = time.monotonic()
    expected_host = session.host.id
    try:
        member = await guild.fetch_member(expected_host)
        if session.host.id==expected_host:
            session.host,session.host_missing = member,False
    except discord.NotFound:
        if session.host.id==expected_host:
            session.host_missing = True
            session.checkpoint()
    except discord.HTTPException:
        log.warning('Não foi possível conferir a presença do anfitrião no servidor %s.',session.guild_id)


async def expire_recovery(session):
    await asyncio.sleep(PAUSE_TIMEOUT)
    if session.running and session.phase=='recovery':
        await session.stop_now('Ninguém retomou a partida salva. Use /adventures quando quiser jogar.')


async def restore_one_session(channel,state):
    existing = active_sessions.get(channel.id)
    if existing and existing.running:
        return existing
    running = [s for s in active_sessions.values() if s.running]
    guild = getattr(channel,'guild',None)
    if (guild is None or str(guild.id)!=str(state['guild_id']) or len(running)>=MAX_SESSIONS
            or sum(s.guild_id==guild.id for s in running)>=MAX_GUILD_SESSIONS):
        return None
    host = SimpleNamespace(id=int(state['host']['id']),display_name=state['host']['name'],bot=False)
    session = QuizSession(channel,host,bot.scores)
    try:
        session.load_saved(state,screen.GROUPS)
    except (ValueError,KeyError,TypeError):
        bot.adventures.save(state,'finished')
        log.warning('Partida salva incompatível no canal %s; pontos preservados.',channel.id)
        return None
    active_sessions[channel.id] = session  # Reserve before any REST lookup or publication.
    try:
        await check_host_presence(session)
        if session.phase=='lobby':
            await session.open_lobby()
        else:
            view = extra_screen.recovery_panel(session,handle_control)
            old_id = state.get('control_message_id')
            message = None
            if old_id and hasattr(channel,'fetch_message'):
                with contextlib.suppress(discord.NotFound):
                    message = await channel.fetch_message(int(old_id))
            if message:
                await message.edit(view=view)
            else:
                message = await channel.send(view=view)
            session.control_message,session.control_view = message,view
            session.remember_panel(resolved=False)
            session.lobby_timer = asyncio.create_task(expire_recovery(session),name=f'recover:{channel.id}')
        return session
    except discord.HTTPException:
        session.running = False
        session.suspending = True
        session.checkpoint('suspended')
        session.release_channel()
        log.exception('Não foi possível apresentar a partida salva no canal %s.',channel.id)
        return None


async def restore_saved_sessions():
    for state in bot.adventures.recoverable():
        if not state:
            continue
        try:
            channel_id = int(state['channel_id'])
            channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
            await restore_one_session(channel,state)
        except (discord.NotFound,discord.Forbidden):
            bot.adventures.save(state,'finished')
            log.warning('Canal de uma partida salva não está mais acessível: %s.',channel_id)
        except discord.HTTPException:
            log.warning('Recuperação adiada no canal %s por falha do Discord.',channel_id)
        except (ValueError,KeyError,TypeError):
            with bot.adventures.connection:
                bot.adventures.connection.execute("UPDATE adventure_sessions SET status='invalid' WHERE id=?",(state['id'],))
            log.warning('Uma partida salva inválida foi isolada; os pontos foram preservados.')


@bot.event
async def on_raw_member_remove(payload):
    for session in list(active_sessions.values()):
        if session.guild_id==payload.guild_id and session.host.id==payload.user.id:
            session.host_missing = True
            session.checkpoint()
            await session.refresh_controls()


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
    await session.stop_now('O painel foi apagado. Use /adventures para jogar de novo.')


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


@bot.event
async def on_thread_delete(thread):
    await on_guild_channel_delete(thread)


@bot.event
async def on_guild_remove(guild):
    sessions = [s for s in list(active_sessions.values()) if s.guild_id == guild.id]
    await asyncio.gather(*(s.stop_now('O bot saiu deste servidor.') for s in sessions))


@bot.tree.command(name='adventures', description='Responda desafios sobre o lançamento de Anime Adventures. Escolha os assuntos e jogue!')
@app_commands.guild_only()
async def adventures(interaction: discord.Interaction):
    await begin_lobby(interaction)


@bot.tree.error
async def on_command_error(interaction, error):
    await respond_to_error(interaction, error)


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('DISCORD_TOKEN não foi encontrado nas variáveis de ambiente.')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    bot.run(token)
