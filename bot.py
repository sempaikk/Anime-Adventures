"""Anime Adventures Release quiz: one command, open answers, one winner."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from quiz_content import QuestionDeck, load_pack
from scores import ScoreStore

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
QUESTION_TIME = 45
COUNTDOWN_INTERVAL = 10
BETWEEN_QUESTIONS = 8
WELCOME_DELAY = 1.5
BRAND_COLOR = 0x31C9B3
GOLD = 0xF4C95D
RARITY_COLORS = {'Rare': 0x4CA9F5, 'Epic': 0xAE70ED, 'Legendary': GOLD, 'Mythic': 0xF05C75}
CATEGORY_ICONS = {
    'Unidades': '⚔️', 'Raridades': '✦', 'Evoluções': '🌟', 'Mundos': '🌏',
    'Chefes': '👑', 'Atos': '📜', 'Comida e XP': '🍜', 'Traits': '💠',
    'Summon': '💎', 'Economia': '🪙', 'Modos': '🎮', 'Missões': '🎯',
    'Loja e códigos': '🎟️', 'Upgrades': '⬆️',
}
PACK = load_pack()
log = logging.getLogger('adventures')
active_sessions: dict[int, QuizSession] = {}


def branded_embed(title, description, color=BRAND_COLOR):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_author(name='ANIME ADVENTURES  /  RELEASE · JUL 2022')
    return embed


class QuizSession:
    def __init__(self, channel, host, store, *, deck=None, clock=None):
        self.channel = channel
        self.host = host
        self.store = store
        self.deck = deck or QuestionDeck(PACK.questions)
        self.clock = clock or time.monotonic
        self.running = False
        self.current_question = None
        self.question_message = None
        self.question_number = 0
        self.had_participation = False
        self.deadline = 0.0
        self.ends_at = None
        self.answer_future = None
        self.runner = None
        self.ticker = None
        self.session_scores: dict[int, dict] = {}
        self.correct_count = 0

    def launch(self):
        self.running = True
        self.runner = asyncio.create_task(self.run(), name=f'quiz:{self.channel.id}')

    def question_embed(self, seconds_remaining):
        question = self.current_question
        icon = CATEGORY_ICONS.get(question.category, '✦')
        embed = branded_embed(
            f'{icon}  {question.category.upper()}  /  {self.question_number:03d}',
            question.prompt,
            RARITY_COLORS.get(question.rarity, BRAND_COLOR),
        )
        if question.rarity:
            embed.add_field(name='✦ RARIDADE', value=question.rarity, inline=True)
        embed.add_field(name='🏆 RECOMPENSA', value='Primeiro acerto: **+1 ponto**', inline=True)
        filled = max(0, min(10, math.ceil(seconds_remaining / QUESTION_TIME * 10)))
        embed.add_field(
            name='⏳ TEMPO PARA RESPONDER',
            value=f"{'▰' * filled}{'▱' * (10 - filled)}  **{math.ceil(seconds_remaining)}s**\n"
                  f'Termina <t:{int(self.ends_at.timestamp())}:R>',
            inline=False,
        )
        embed.set_footer(text='Responda no chat • vale a primeira resposta correta • sem alternativas')
        return embed

    def standings(self):
        leaders = sorted(self.session_scores.values(), key=lambda entry: (-entry['points'], entry['first']))[:5]
        medals = ['🥇', '🥈', '🥉', '④', '⑤']
        return '\n'.join(
            f"{medals[index]} **{discord.utils.escape_markdown(entry['name'])}** · {entry['points']} pts"
            for index, entry in enumerate(leaders)
        ) or 'O primeiro ponto ainda está em jogo.'

    def result_embed(self, winner, total_points, continuing):
        question = self.current_question
        title = '✦ RESPOSTA CERTA!' if winner else '⌛ TEMPO ESGOTADO'
        who = f'**{discord.utils.escape_markdown(winner.display_name)}** acertou primeiro. **+1 ponto!**' if winner else 'Desta vez ninguém acertou a tempo.'
        embed = branded_embed(title, f'{who}\n\n**{question.answer}**\n{question.explanation}', 0x4AD99B if winner else GOLD)
        if winner and total_points is not None:
            embed.add_field(name='💎 SEU TOTAL ACUMULADO', value=f'**{total_points} pontos**', inline=False)
        elif winner:
            embed.add_field(name='PONTUAÇÃO', value='+1 nesta sessão. Não foi possível salvar o total acumulado agora.', inline=False)
        embed.add_field(name='🏆 PLACAR DESTA SESSÃO', value=self.standings(), inline=False)
        if continuing:
            next_at = int((datetime.now(timezone.utc) + timedelta(seconds=BETWEEN_QUESTIONS)).timestamp())
            embed.add_field(name='PRÓXIMA PERGUNTA', value=f'<t:{next_at}:R> · **{BETWEEN_QUESTIONS}s** para respirar.', inline=False)
            embed.set_footer(text='Release • perguntas variadas, sem repetir até completar o baralho')
        else:
            embed.add_field(name='SESSÃO ENCERRADA', value='Ninguém participou desta pergunta. Use **/adventures** para jogar novamente.', inline=False)
            embed.set_footer(text=f'{self.question_number} perguntas • {self.correct_count} acertos • até a próxima aventura!')
        return embed

    def source_view(self):
        source = PACK.sources[self.current_question.sources[0]]
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label='Conferir na wiki', url=source['url'], emoji='📖'))
        return view

    def submit(self, message):
        """Claim synchronously: no await can let a second answer win this question."""
        if (not self.running or self.question_message is None or self.answer_future is None
                or self.answer_future.done() or self.clock() >= self.deadline):
            return False
        if (message.author.bot or message.webhook_id is not None
                or message.id <= self.question_message.id):
            return False
        self.had_participation = True
        if self.current_question.accepts(message.content):
            self.answer_future.set_result(message.author)
            return True
        return False

    async def update_clock(self, refresh_immediately=False):
        first = True
        while True:
            remaining = self.deadline - self.clock()
            if remaining <= 0:
                return
            if not (first and refresh_immediately):
                await asyncio.sleep(min(COUNTDOWN_INTERVAL, remaining))
            first = False
            remaining = self.deadline - self.clock()
            if remaining <= 0 or self.answer_future.done():
                return
            try:
                await self.question_message.edit(embed=self.question_embed(remaining))
            except (discord.NotFound, discord.Forbidden):
                # A deleted or inaccessible question cannot be answered fairly.
                self.answer_future.cancel()
                return
            except discord.HTTPException:
                # Cosmetic edits cannot extend the independent answer deadline.
                log.warning('Não foi possível atualizar o relógio no canal %s', self.channel.id)

    async def stop_ticker(self):
        if self.ticker:
            self.ticker.cancel()
            # A failed cosmetic update must never prevent session cleanup.
            results = await asyncio.gather(self.ticker, return_exceptions=True)
            if isinstance(results[0], Exception):
                log.error('Falha no relógio do canal %s: %s', self.channel.id, type(results[0]).__name__)
            self.ticker = None

    async def play_question(self):
        self.question_number += 1
        self.question_message = None
        self.had_participation = False
        self.current_question = self.deck.draw()
        self.answer_future = asyncio.get_running_loop().create_future()
        publishing_started = self.clock()
        self.deadline = publishing_started + QUESTION_TIME
        self.ends_at = datetime.now(timezone.utc) + timedelta(seconds=QUESTION_TIME)
        self.question_message = await self.channel.send(embed=self.question_embed(QUESTION_TIME))
        # Discord rate limits or a slow send must not consume the player's 45 seconds.
        publish_lag = self.clock() - publishing_started
        self.deadline = self.clock() + QUESTION_TIME
        self.ends_at = datetime.now(timezone.utc) + timedelta(seconds=QUESTION_TIME)
        self.ticker = asyncio.create_task(self.update_clock(publish_lag >= 1), name=f'clock:{self.channel.id}')
        try:
            winner = await asyncio.wait_for(self.answer_future, max(0, self.deadline - self.clock()))
        except asyncio.TimeoutError:
            winner = None
        finally:
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
        closed = branded_embed(
            f"{CATEGORY_ICONS.get(self.current_question.category, '✦')}  {self.current_question.category.upper()}  /  {self.question_number:03d}",
            self.current_question.prompt,
            RARITY_COLORS.get(self.current_question.rarity, BRAND_COLOR),
        )
        closed.set_footer(text='Pergunta encerrada • resposta e placar logo abaixo')
        with contextlib.suppress(discord.HTTPException):
            await self.question_message.edit(embed=closed)
        continuing = self.had_participation
        await self.channel.send(embed=self.result_embed(winner, total, continuing), view=self.source_view())
        return continuing

    async def run(self):
        try:
            welcome = branded_embed(
                '✦ SUA AVENTURA COMEÇA AQUI',
                f'**{discord.utils.escape_markdown(self.host.display_name)}** abriu o quiz do Release.\n'
                'De Planet Namak às primeiras unidades: quanto você lembra?',
            )
            welcome.add_field(name='⚔️ COMO JOGAR', value='Todo mundo responde **no chat**. O primeiro acerto vale **1 ponto**; você também pode jogar sozinho.', inline=False)
            welcome.add_field(name='⏳ RITMO', value=f'**{QUESTION_TIME}s** por pergunta · **{BETWEEN_QUESTIONS}s** entre elas.', inline=False)
            welcome.add_field(name='🌏 NESTA AVENTURA', value='Unidades, raridades, evoluções, mundos, chefes, atos, comida, XP, traits, summon, missões, economia, loja e upgrades.', inline=False)
            welcome.set_footer(text='Sem participação, a sessão termina sozinha • /adventures para começar outra')
            await self.channel.send(embed=welcome)
            await asyncio.sleep(WELCOME_DELAY)
            while self.running:
                if not await self.play_question():
                    break
                await asyncio.sleep(BETWEEN_QUESTIONS)
        except asyncio.CancelledError:
            raise
        except discord.HTTPException:
            log.exception('Sessão interrompida por erro do Discord no canal %s', self.channel.id)
            with contextlib.suppress(discord.HTTPException):
                await self.channel.send('A sessão foi interrompida. Confira as permissões do canal e use **/adventures** para tentar novamente.')
        except Exception:
            log.exception('Erro na sessão do canal %s', self.channel.id)
            with contextlib.suppress(discord.HTTPException):
                await self.channel.send('A sessão precisou ser encerrada. Você pode iniciar outra com **/adventures**.')
        finally:
            self.running = False
            if self.answer_future and not self.answer_future.done():
                self.answer_future.cancel()
            await self.stop_ticker()
            if active_sessions.get(self.channel.id) is self:
                del active_sessions[self.channel.id]


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
        # Once per process, rather than once per Gateway reconnect.
        synced = await self.tree.sync()
        log.info('%s comando(s) sincronizado(s); %s perguntas Release', len(synced), len(PACK.questions))

    async def close(self):
        tasks = [session.runner for session in list(active_sessions.values()) if session.runner]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.scores:
            self.scores.close()
            self.scores = None
        await super().close()


bot = AdventuresBot()


@bot.event
async def on_ready():
    log.info('Conectado como %s; %s sessões ativas', bot.user, len(active_sessions))


@bot.event
async def on_message(message: discord.Message):
    if not message.author.bot:
        session = active_sessions.get(message.channel.id)
        if session:
            session.submit(message)


@bot.tree.command(name='adventures', description='Jogue o quiz do Release de Anime Adventures neste canal.')
@app_commands.guild_only()
async def adventures(interaction: discord.Interaction):
    channel = interaction.channel
    if channel is None or not hasattr(channel, 'send') or interaction.guild is None:
        await interaction.response.send_message('Use este comando em um canal de texto do servidor.', ephemeral=True)
        return
    permissions = interaction.app_permissions
    can_send = permissions.send_messages_in_threads if isinstance(channel, discord.Thread) else permissions.send_messages
    if not (permissions.view_channel and can_send and permissions.embed_links):
        await interaction.response.send_message('Preciso das permissões **Ver canal**, **Enviar mensagens** e **Inserir links** para apresentar o quiz aqui.', ephemeral=True)
        return
    existing = active_sessions.get(channel.id)
    if existing and existing.running:
        await interaction.response.send_message('Já tem uma aventura acontecendo aqui! Responda à pergunta no chat.', ephemeral=True)
        return
    session = QuizSession(channel, interaction.user, bot.scores)
    session.running = True
    active_sessions[channel.id] = session
    try:
        await interaction.response.send_message('✦ Preparando a aventura neste canal…', ephemeral=True)
    except BaseException:
        if active_sessions.get(channel.id) is session:
            del active_sessions[channel.id]
        raise
    session.launch()


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('DISCORD_TOKEN não foi encontrado nas variáveis de ambiente.')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    bot.run(token)
