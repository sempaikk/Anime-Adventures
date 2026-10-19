import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import random
import asyncio
from datetime import datetime, timezone

TOKEN = os.getenv("DISCORD_TOKEN")
UNITS_FILE = "units.json"
SCORES_FILE = "scores.json"

QUESTION_TIME = 45
WARNING_TIME = 15          # avisa quando faltar 15s
BETWEEN_QUESTIONS = 8

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

def load_units():
    with open(UNITS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_scores():
    if not os.path.exists(SCORES_FILE):
        return {}
    try:
        with open(SCORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_scores(scores):
    with open(SCORES_FILE, "w", encoding="utf-8") as f:
        json.dump(scores, f, indent=2, ensure_ascii=False)

UNITS = load_units()
active_sessions = {}

def normalize(text: str) -> str:
    return text.lower().strip().replace("-", " ").replace("_", " ").replace("  ", " ")

def check_answer(user_answer: str, unit: dict) -> bool:
    user_answer = normalize(user_answer)
    possible = [normalize(unit["name"])] + [normalize(a) for a in unit.get("aliases", [])]
    return user_answer in possible

def add_point(user_id: int, username: str):
    scores = load_scores()
    uid = str(user_id)
    if uid not in scores:
        scores[uid] = {"name": username, "points": 0, "correct": 0}
    scores[uid]["points"] += 1
    scores[uid]["correct"] += 1
    scores[uid]["name"] = username
    save_scores(scores)

class QuizSession:
    def __init__(self, channel: discord.TextChannel, host: discord.Member):
        self.channel = channel
        self.host = host
        self.running = True
        self.current_unit = None
        self.question_number = 0
        self.answered = False
        self.had_participation = False
        self.question_message = None
        self.warning_sent = False

    async def start(self):
        embed = discord.Embed(
            title="Anime Adventures Quiz",
            description=(
                f"Iniciado por {self.host.mention}\n\n"
                f"• Digite o **nome da unidade** no chat\n"
                f"• O **primeiro** que acertar ganha ponto\n"
                f"• Tempo por pergunta: **{QUESTION_TIME} segundos**\n\n"
                f"Boa sorte!"
            ),
            color=0x9B59B6
        )
        embed.set_footer(text="Release Units Only")
        await self.channel.send(embed=embed)
        await asyncio.sleep(2)
        await self.next_question()

    async def next_question(self):
        if not self.running:
            return

        self.question_number += 1
        self.answered = False
        self.had_participation = False
        self.warning_sent = False
        self.current_unit = random.choice(UNITS)

        embed = discord.Embed(
            title=f"Pergunta #{self.question_number}",
            color=0x8E44AD
        )
        embed.add_field(name="Raridade", value=f"`{self.current_unit['rarity']}`", inline=True)
        embed.add_field(name="Tipo", value=f"`{self.current_unit['type']}`", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(
            name="Dica",
            value=self.current_unit["hint"],
            inline=False
        )
        embed.set_footer(text=f"Tempo restante: {QUESTION_TIME}s  •  Digite o nome no chat")
        embed.timestamp = datetime.now(timezone.utc)

        self.question_message = await self.channel.send(embed=embed)

        # Timer com aviso
        try:
            await asyncio.sleep(QUESTION_TIME - WARNING_TIME)
            if not self.answered and self.running and not self.warning_sent:
                self.warning_sent = True
                await self.channel.send(f"⏳ **{WARNING_TIME} segundos** restantes...", delete_after=WARNING_TIME)

            await asyncio.sleep(WARNING_TIME)
            if not self.answered and self.running:
                await self.finish_question(None)
        except asyncio.CancelledError:
            pass

    async def finish_question(self, winner: discord.Member | None):
        if self.answered:
            return
        self.answered = True

        if winner:
            add_point(winner.id, winner.display_name)
            embed = discord.Embed(
                title="Acertou!",
                description=f"**{winner.display_name}** acertou primeiro!\n\nResposta correta: **{self.current_unit['name']}**\n+1 ponto",
                color=0x2ECC71
            )
        else:
            embed = discord.Embed(
                title="Tempo esgotado",
                description=f"Ninguém acertou a tempo.\n\nResposta correta: **{self.current_unit['name']}**",
                color=0xE74C3C
            )

        await self.channel.send(embed=embed)

        # Lógica de participação
        if not self.had_participation:
            end_embed = discord.Embed(
                title="Quiz encerrado",
                description="Ninguém participou desta pergunta. Encerrando automaticamente.",
                color=0x95A5A6
            )
            await self.channel.send(embed=end_embed)
            self.running = False
            if self.channel.id in active_sessions:
                del active_sessions[self.channel.id]
            return

        await asyncio.sleep(BETWEEN_QUESTIONS)
        if self.running:
            await self.next_question()

@bot.event
async def on_ready():
    print(f"Logado como {bot.user} (ID: {bot.user.id})")
    try:
        synced = await tree.sync()
        print(f"Comandos sincronizados: {len(synced)}")
    except Exception as e:
        print("Erro ao sincronizar:", e)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    session = active_sessions.get(message.channel.id)
    if not session or not session.running or session.answered:
        return

    # Qualquer mensagem = participação
    session.had_participation = True

    if check_answer(message.content, session.current_unit):
        session.answered = True
        await session.finish_question(message.author)

@tree.command(name="adventures", description="Inicia o quiz de Anime Adventures (Release Units)")
async def adventures(interaction: discord.Interaction):
    channel = interaction.channel

    if channel.id in active_sessions and active_sessions[channel.id].running:
        await interaction.response.send_message("Já existe um quiz rodando neste canal.", ephemeral=True)
        return

    session = QuizSession(channel, interaction.user)
    active_sessions[channel.id] = session

    await interaction.response.send_message("Iniciando o quiz...", ephemeral=True)
    await session.start()

if __name__ == "__main__":
    if not TOKEN:
        print("ERRO: DISCORD_TOKEN não encontrado!")
    else:
        bot.run(TOKEN)
