import asyncio
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands


BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("DISCORD_TOKEN")
UNITS_FILE = BASE_DIR / "units.json"
SCORES_FILE = BASE_DIR / "scores.json"

QUESTION_TIME = 45
COUNTDOWN_INTERVAL = 10
BETWEEN_QUESTIONS = 8

RARITY_COLORS = {
    "Rare": 0x3498DB,       # azul
    "Epic": 0x9B59B6,       # roxo
    "Legendary": 0xF1C40F,  # dourado/amarelo
    "Mythic": 0xE74C3C,     # vermelho
    "Secret": 0x1ABC9C,     # verde-azulado
    "Exclusive": 0xE67E22,  # laranja
}
DEFAULT_COLOR = 0x5865F2

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
tree = bot.tree
active_sessions = {}


def load_units():
    try:
        with UNITS_FILE.open("r", encoding="utf-8") as file:
            units = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Não foi possível carregar units.json: {exc}") from exc

    if not isinstance(units, list) or not units:
        raise ValueError("units.json precisa conter uma lista não vazia de unidades.")

    required_fields = ("name", "rarity", "type", "hint")
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise ValueError(f"A unidade de índice {index} não é um objeto JSON.")
        missing = [field for field in required_fields if not unit.get(field)]
        if missing:
            raise ValueError(f"Unidade de índice {index} sem os campos: {', '.join(missing)}")
        if not isinstance(unit.get("aliases", []), list):
            raise ValueError(f"Os aliases da unidade {unit['name']} precisam ser uma lista.")

    return units


def load_scores():
    if not SCORES_FILE.exists():
        return {}
    try:
        with SCORES_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_scores(scores):
    temp_file = SCORES_FILE.with_suffix(".tmp")
    temp_file.write_text(
        json.dumps(scores, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temp_file.replace(SCORES_FILE)


def add_point(user_id: int, username: str) -> int:
    scores = load_scores()
    uid = str(user_id)

    if uid not in scores or not isinstance(scores[uid], dict):
        scores[uid] = {"name": username, "points": 0, "correct": 0}

    scores[uid]["name"] = username
    scores[uid]["points"] = int(scores[uid].get("points", 0)) + 1
    scores[uid]["correct"] = int(scores[uid].get("correct", 0)) + 1
    save_scores(scores)
    return scores[uid]["points"]


def normalize_answer(value: str) -> str:
    """Normaliza caixa e espaços; não tenta corrigir erros de digitação."""
    value = value.casefold().replace("-", " ").replace("_", " ")
    return " ".join(value.split())


def check_answer(user_answer: str, unit: dict) -> bool:
    accepted_names = [
        unit.get("name", ""),
        unit.get("anime_name", ""),
        *unit.get("aliases", []),
    ]
    accepted = {normalize_answer(name) for name in accepted_names if name}
    return normalize_answer(user_answer) in accepted


def correct_answer_label(unit: dict) -> str:
    wiki_name = unit["name"]
    anime_name = unit.get("anime_name")
    if anime_name and normalize_answer(anime_name) != normalize_answer(wiki_name):
        return f"{wiki_name} — {anime_name}"
    return wiki_name


UNITS = load_units()


class QuizSession:
    def __init__(self, channel, host):
        self.channel = channel
        self.host = host
        self.running = True
        self.current_unit = None
        self.question_number = 0
        self.answered = False
        self.had_participation = False
        self.question_message = None
        self.question_started_at = None
        self.timer_task = None
        self.unit_deck = []

    def draw_unit(self):
        # Evita repetir uma unidade até que todas as unidades da lista tenham saído.
        if not self.unit_deck:
            self.unit_deck = UNITS.copy()
            random.shuffle(self.unit_deck)
        return self.unit_deck.pop()

    def make_question_embed(self, seconds_remaining: int):
        unit = self.current_unit
        embed = discord.Embed(
            title="🧩 QUEM É ESSA UNIDADE?",
            description=(
                "Descubra o personagem do **release de Anime Adventures**.\n"
                "Digite o nome no chat. O primeiro acerto ganha **1 ponto**."
            ),
            color=RARITY_COLORS.get(unit["rarity"], DEFAULT_COLOR),
        )
        embed.set_author(name="ANIME ADVENTURES  •  RELEASE QUIZ")
        embed.add_field(
            name="✦ RARIDADE",
            value=f"**{unit['rarity']}**",
            inline=True,
        )
        embed.add_field(
            name="⚔️ TIPO",
            value=f"**{unit['type']}**",
            inline=True,
        )
        embed.add_field(
            name="🔎 DICA",
            value=unit["hint"],
            inline=False,
        )
        embed.set_footer(
            text=(
                f"Pergunta #{self.question_number}  •  "
                f"Tempo restante: {seconds_remaining}s  •  "
                "Nomes oficiais, sem diferenciar maiúsculas/minúsculas"
            )
        )
        embed.timestamp = self.question_started_at
        return embed

    async def start(self):
        welcome = discord.Embed(
            title="🎮 ANIME ADVENTURES QUIZ",
            description=(
                f"Rodada iniciada por {self.host.mention}.\n\n"
                "Prepare sua memória de anime: a pergunta aparece aqui e "
                "todo mundo pode responder no chat."
            ),
            color=DEFAULT_COLOR,
        )
        welcome.add_field(
            name="COMO JOGAR",
            value=(
                "Digite o nome do personagem diretamente no chat. "
                "Não há botões nem alternativas."
            ),
            inline=False,
        )
        welcome.add_field(
            name="PONTUAÇÃO",
            value="O primeiro jogador que acertar recebe **+1 ponto**.",
            inline=True,
        )
        welcome.add_field(
            name="TEMPO",
            value=(
                f"**{QUESTION_TIME} segundos** por pergunta. "
                "O relógio é atualizado a cada 10 segundos."
            ),
            inline=True,
        )
        welcome.set_footer(
            text=(
                "A rodada para sozinha se ninguém participar. "
                "Envie /adventures para iniciar outra."
            )
        )
        await self.channel.send(embed=welcome)
        await asyncio.sleep(1.5)
        await self.ask_question()

    async def ask_question(self):
        if not self.running:
            return

        self.question_number += 1
        self.answered = False
        self.had_participation = False
        self.current_unit = self.draw_unit()
        self.question_started_at = datetime.now(timezone.utc)

        embed = self.make_question_embed(QUESTION_TIME)
        self.question_message = await self.channel.send(embed=embed)

        # Timer separado para que cada pergunta tenha seu próprio relógio.
        self.timer_task = asyncio.create_task(
            self.run_timer(self.question_number)
        )

    async def run_timer(self, question_number: int):
        remaining = QUESTION_TIME
        try:
            while remaining > 0:
                interval = min(COUNTDOWN_INTERVAL, remaining)
                await asyncio.sleep(interval)
                remaining -= interval

                if (
                    not self.running
                    or self.answered
                    or question_number != self.question_number
                ):
                    return

                if self.question_message:
                    try:
                        await self.question_message.edit(
                            embed=self.make_question_embed(remaining)
                        )
                    except discord.HTTPException:
                        # Mantém o timer mesmo se uma edição da embed falhar.
                        pass

            if (
                self.running
                and not self.answered
                and question_number == self.question_number
            ):
                await self.finish_question(None)
        except asyncio.CancelledError:
            return

    async def finish_question(self, winner=None):
        # O estado é marcado antes do primeiro await para impedir dois vencedores.
        if self.answered or not self.running:
            return
        self.answered = True

        current_task = asyncio.current_task()
        if self.timer_task and self.timer_task is not current_task:
            self.timer_task.cancel()

        answer = correct_answer_label(self.current_unit)

        if winner is not None:
            total_points = add_point(winner.id, winner.display_name)
            result = discord.Embed(
                title="✅ RESPOSTA CORRETA!",
                description=(
                    f"{winner.mention} foi o primeiro a acertar!\n\n"
                    f"**Resposta:** {answer}\n"
                    f"**Pontos nesta rodada:** +1\n"
                    f"**Pontuação acumulada:** {total_points}"
                ),
                color=0x57F287,
            )
            result.set_footer(text="Boa! A próxima pergunta vem em alguns segundos.")
        else:
            result = discord.Embed(
                title="⏰ TEMPO ESGOTADO",
                description=(
                    f"Ninguém acertou a tempo.\n\n"
                    f"**Resposta correta:** {answer}"
                ),
                color=0xED4245,
            )

        await self.channel.send(embed=result)

        if not self.had_participation:
            ending = discord.Embed(
                title="🛑 QUIZ ENCERRADO",
                description=(
                    "Ninguém enviou mensagem durante esta pergunta, então a rodada "
                    "foi encerrada automaticamente.\n\n"
                    "Use **/adventures** para começar de novo."
                ),
                color=0x95A5A6,
            )
            ending.set_footer(text=f"{self.question_number} pergunta(s) exibida(s)")
            await self.channel.send(embed=ending)
            self.running = False
            if active_sessions.get(self.channel.id) is self:
                del active_sessions[self.channel.id]
            return

        await asyncio.sleep(BETWEEN_QUESTIONS)
        if self.running:
            await self.ask_question()


@bot.event
async def on_ready():
    print(f"Conectado como {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"Comandos de barra sincronizados: {len(synced)}")
    except Exception as exc:
        print(f"Falha ao sincronizar comandos: {exc}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    session = active_sessions.get(message.channel.id)
    if (
        session is None
        or not session.running
        or session.answered
        or session.current_unit is None
        or session.question_message is None
    ):
        return

    # Só contam mensagens publicadas depois da pergunta atual.
    if message.created_at < session.question_message.created_at:
        return

    # Até uma tentativa errada conta como participação; não existe dica de "quase".
    session.had_participation = True

    if check_answer(message.content, session.current_unit):
        await session.finish_question(message.author)


@tree.command(
    name="adventures",
    description="Inicia o quiz de lançamento de Anime Adventures neste canal.",
)
async def adventures(interaction: discord.Interaction):
    channel = interaction.channel
    if channel is None or not hasattr(channel, "send"):
        await interaction.response.send_message(
            "Não consegui identificar um canal de texto para iniciar o quiz.",
            ephemeral=True,
        )
        return

    existing = active_sessions.get(channel.id)
    if existing and existing.running:
        await interaction.response.send_message(
            "Já existe uma rodada ativa neste canal.",
            ephemeral=True,
        )
        return

    session = QuizSession(channel, interaction.user)
    active_sessions[channel.id] = session

    await interaction.response.send_message(
        f"🎮 Quiz iniciado em {channel.mention}. Boa sorte!",
        ephemeral=True,
    )
    await session.start()


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN não foi encontrado nas variáveis de ambiente."
        )
    bot.run(TOKEN)
