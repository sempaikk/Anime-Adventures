import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import random
import asyncio
from datetime import datetime, timezone

# ================== CONFIG ==================
TOKEN = os.getenv("DISCORD_TOKEN")
UNITS_FILE = "units.json"
SCORES_FILE = "scores.json"
QUESTION_TIME = 40          # segundos para responder
BETWEEN_QUESTIONS = 12      # segundos entre perguntas
MAX_QUESTIONS = 15          # máximo de perguntas por sessão

intents = discord.Intents.default()
intents.message_content = True
intents.members = False

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ================== DADOS ==================
def load_units():
    with open(UNITS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_scores():
    if not os.path.exists(SCORES_FILE):
        return {}
    with open(SCORES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_scores(scores):
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)

UNITS = load_units()
active_sessions = {}  # channel_id: session data

# ================== HELPERS ==================
def normalize(text: str) -> str:
    return text.lower().strip().replace("-", " ").replace("_", " ")

def check_answer(user_answer: str, unit: dict) -> bool:
    user_answer = normalize(user_answer)
    correct_names = [normalize(unit["name"])] + [normalize(a) for a in unit.get("aliases", [])]
    return user_answer in correct_names

def add_point(user_id: int, username: str):
    scores = load_scores()
    uid = str(user_id)
    if uid not in scores:
        scores[uid] = {"name": username, "points": 0, "correct": 0}
    scores[uid]["points"] += 1
    scores[uid]["correct"] += 1
    scores[uid]["name"] = username
    save_scores(scores)

# ================== SESSÃO DE QUIZ ==================
class QuizSession:
    def __init__(self, channel: discord.TextChannel, host: discord.Member):
        self.channel = channel
        self.host = host
        self.running = True
        self.current_unit = None
        self.question_number = 0
        self.answered = False
        self.message = None
        self.task = None

    async def start(self):
        await self.channel.send(
            f"**Anime Adventures Quiz iniciado por {self.host.mention}!**\n"
            f"Digite o nome da unidade no chat. Primeiro que acertar ganha ponto.\n"
            f"Tempo por pergunta: **{QUESTION_TIME}s**"
        )
        await asyncio.sleep(3)
        await self.next_question()

    async def next_question(self):
        if not self.running or self.question_number >= MAX_QUESTIONS:
            await self.end()
            return

        self.question_number += 1
        self.answered = False
        self.current_unit = random.choice(UNITS)

        embed = discord.Embed(
            title=f"Pergunta {self.question_number}/{MAX_QUESTIONS}",
            description=(
                f"**Qual é essa unidade?**\n\n"
                f"**Raridade:** {self.current_unit['rarity']}\n"
                f"**Tipo:** {self.current_unit['type']}\n"
                f"**Dica:** {self.current_unit['hint']}"
            ),
            color=discord.Color.purple()
        )
        embed.set_footer(text=f"Você tem {QUESTION_TIME} segundos • Digite o nome no chat")

        self.message = await self.channel.send(embed=embed)

        # Timer
        try:
            await asyncio.sleep(QUESTION_TIME)
            if not self.answered and self.running:
                await self.reveal_answer(None)
        except asyncio.CancelledError:
            pass

    async def reveal_answer(self, winner: discord.Member | None):
        if self.answered:
            return
        self.answered = True

        if winner:
            add_point(winner.id, winner.display_name)
            text = f"**{winner.display_name}** acertou! +1 ponto\nResposta: **{self.current_unit['name']}**"
            color = discord.Color.green()
        else:
            text = f"Ninguém acertou a tempo.\nResposta: **{self.current_unit['name']}**"
            color = discord.Color.red()

        embed = discord.Embed(description=text, color=color)
        await self.channel.send(embed=embed)

        await asyncio.sleep(BETWEEN_QUESTIONS)
        if self.running:
            await self.next_question()

    async def end(self):
        self.running = False
        if self.channel.id in active_sessions:
            del active_sessions[self.channel.id]

        scores = load_scores()
        top = sorted(scores.items(), key=lambda x: x[1]["points"], reverse=True)[:5]

        description = "**Ranking atual do servidor:**\n\n"
        if top:
            for i, (uid, data) in enumerate(top, 1):
                description += f"**{i}.** {data['name']} — {data['points']} pts\n"
        else:
            description += "Ninguém pontuou ainda."

        embed = discord.Embed(
            title="Quiz finalizado!",
            description=description,
            color=discord.Color.gold()
        )
        await self.channel.send(embed=embed)

# ================== EVENTOS ==================
@bot.event
async def on_ready():
    print(f"Logado como {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print(f"Erro ao sincronizar: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    session = active_sessions.get(message.channel.id)
    if not session or not session.running or session.answered:
        return

    if check_answer(message.content, session.current_unit):
        session.answered = True
        await session.reveal_answer(message.author)

# ================== COMANDO /adventures ==================
@tree.command(name="adventures", description="Inicia ou gerencia o quiz de Anime Adventures")
@app_commands.describe(
    action="O que você quer fazer"
)
@app_commands.choices(action=[
    app_commands.Choice(name="start", value="start"),
    app_commands.Choice(name="stop", value="stop"),
    app_commands.Choice(name="rank", value="rank"),
])
async def adventures(interaction: discord.Interaction, action: app_commands.Choice[str]):
    channel = interaction.channel

    if action.value == "start":
        if channel.id in active_sessions and active_sessions[channel.id].running:
            await interaction.response.send_message("Já existe um quiz rodando neste canal!", ephemeral=True)
            return

        session = QuizSession(channel, interaction.user)
        active_sessions[channel.id] = session
        await interaction.response.send_message("Iniciando quiz...", ephemeral=True)
        await session.start()

    elif action.value == "stop":
        session = active_sessions.get(channel.id)
        if not session or not session.running:
            await interaction.response.send_message("Não há quiz ativo neste canal.", ephemeral=True)
            return

        session.running = False
        await session.end()
        await interaction.response.send_message("Quiz parado.", ephemeral=True)

    elif action.value == "rank":
        scores = load_scores()
        top = sorted(scores.items(), key=lambda x: x[1]["points"], reverse=True)[:10]

        if not top:
            await interaction.response.send_message("Ninguém pontuou ainda.", ephemeral=True)
            return

        description = ""
        for i, (uid, data) in enumerate(top, 1):
            description += f"**{i}.** {data['name']} — **{data['points']}** pts ({data['correct']} acertos)\n"

        embed = discord.Embed(
            title="Ranking Anime Adventures Quiz",
            description=description,
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )
        await interaction.response.send_message(embed=embed)

# ================== INICIAR ==================
if __name__ == "__main__":
    if not TOKEN:
        print("ERRO: DISCORD_TOKEN não encontrado nas variáveis de ambiente!")
    else:
        bot.run(TOKEN)
