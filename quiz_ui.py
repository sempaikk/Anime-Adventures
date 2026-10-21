"""Native Discord Components V2 screens and controls, shared by desktop and mobile."""

from __future__ import annotations

import logging
import math

import discord
from discord import ui

import quiz_media as media

BRAND_COLOR = 0x8664E8
GOLD = 0xF4C95D
SUCCESS = 0x50D6A0
RARITY_COLORS = {'Rare': 0x4CA9F5, 'Epic': 0xAE70ED, 'Legendary': GOLD, 'Mythic': 0xF05C75}
RARITY_LABELS = {'Rare': 'Rara', 'Epic': 'Épica', 'Legendary': 'Lendária', 'Mythic': 'Mítica'}
CATEGORY_ICONS = {
    'Unidades': '⚔️', 'Raridades': '✦', 'Evoluções': '🌟', 'Mundos': '🌏',
    'Chefes': '👑', 'Atos': '📜', 'Comida e XP': '🍜', 'Traits': '💠',
    'Summon': '💎', 'Economia': '🪙', 'Modos': '🎮', 'Missões': '🎯',
    'Loja e códigos': '🎟️', 'Upgrades': '⬆️',
}
GROUPS = {
    'all': ('Aventura completa', None, 'Todas as categorias do Release'),
    'characters': ('Personagens', {'Unidades', 'Raridades', 'Evoluções', 'Upgrades'}, 'Identidade, raridades, evoluções e upgrades'),
    'worlds': ('Mundos e chefes', {'Mundos', 'Chefes', 'Atos'}, 'Explore os quatro mundos do lançamento'),
    'systems': ('Sistemas do jogo', {'Comida e XP', 'Traits', 'Summon', 'Economia', 'Modos', 'Missões', 'Loja e códigos'}, 'Comida, XP, traits, summon, missões e economia'),
}
BRAND = '-# ANIME ADVENTURES  ✦  RELEASE · JULHO DE 2022'
log = logging.getLogger('adventures.ui')


def safe_name(value):
    # Directional controls can visually reorder a score row; preserve normal Unicode names.
    value = ''.join(c for c in value if c not in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value[:80]))


def text(value):
    return ui.TextDisplay(value)


def divider():
    return ui.Separator(spacing=discord.SeparatorSpacing.small)


class ActionButton(ui.Button):
    def __init__(self, action, callback, *, label, emoji=None, style=discord.ButtonStyle.secondary, disabled=False):
        super().__init__(label=label, emoji=emoji, style=style, disabled=disabled, custom_id=f'aa:{action}')
        self.action = action
        self.dispatch = callback

    async def callback(self, interaction):
        await self.dispatch(interaction, self.action)


class ChoiceSelect(ui.Select):
    def __init__(self, kind, callback, options, placeholder):
        super().__init__(custom_id=f'aa:{kind}', options=options, placeholder=placeholder)
        self.kind = kind
        self.dispatch = callback

    async def callback(self, interaction):
        await self.dispatch(interaction, self.kind, self.values[0])


class Panel(ui.LayoutView):
    def __init__(self, *children, color=BRAND_COLOR, header=None, footer=()):
        super().__init__(timeout=None)
        if header:
            self.add_item(ui.Container(*header, accent_color=color))
        self.card = ui.Container(*children, accent_color=color)
        self.add_item(self.card)
        for item in footer:
            self.add_item(item)

    def retire(self):
        for item in self.walk_children():
            if isinstance(item, (ui.Button, ui.Select)) and not getattr(item, 'url', None):
                item.disabled = True
        self.stop()

    async def on_error(self, interaction, error, item):
        log.error('Erro no controle %s: %s', getattr(item, 'custom_id', '?'), type(error).__name__, exc_info=error)
        message = 'Não consegui concluir esse comando. Tente novamente no painel mais recente.'
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)


def utilities(callback):
    return ui.ActionRow(
        ActionButton('scores', callback, label='Placar', emoji='🏆'),
        ActionButton('help', callback, label='Como jogar', emoji='📖'),
    )


def session_controls(session, callback):
    paused = session.is_paused
    return ui.ActionRow(
        ActionButton('resume' if paused else 'pause', callback,
                     label='Retomar' if paused else 'Pausar',
                     emoji='▶️' if paused else '⏸️', style=discord.ButtonStyle.success if paused else discord.ButtonStyle.secondary),
        ActionButton('stop', callback, label='Fim marcado' if session.stop_requested else 'Encerrar',
                     emoji='⏹️', style=discord.ButtonStyle.danger, disabled=session.stop_requested),
    )


def artwork(index=0):
    asset = media.banner(index)
    return [ui.MediaGallery(discord.MediaGalleryItem(asset['url'], description=asset['alt']))] if asset else []


def illustrated(content, asset):
    if asset and asset['display'] == 'portrait':
        return [ui.Section(text(content), accessory=ui.Thumbnail(asset['url'], description=asset['alt']))]
    if asset:
        return [text(content), ui.MediaGallery(discord.MediaGalleryItem(asset['url'], description=asset['alt']))]
    return [text(content)]


def lobby_panel(session, callback):
    selected = session.selected_questions()
    count = len(selected)
    group = GROUPS[session.group][0]
    categories = len({q.category for q in selected})
    category_menu = ChoiceSelect('category', callback, [
        discord.SelectOption(label=label, value=key, description=description, default=key == session.group)
        for key, (label, _, description) in GROUPS.items()
    ], 'Escolha os assuntos da aventura')
    time_menu = ChoiceSelect('time', callback, [
        discord.SelectOption(label=f'{seconds} segundos', value=str(seconds), description=description, default=seconds == session.question_time)
        for seconds, description in [(30, 'Ritmo rápido'), (45, 'Ritmo clássico · recomendado'), (60, 'Mais tempo para pensar')]
    ], 'Escolha o tempo de resposta')
    return Panel(
        text('## Prepare sua aventura\nEscolha os assuntos, ajuste o tempo e reúna o canal.'),
        text(f'**{group}**\n{count} perguntas · {categories} categorias · **{session.question_time:g}s** por pergunta\nPrimeiro acerto vale **1 ponto**'),
        divider(), text('### 01 · Assuntos'), ui.ActionRow(category_menu),
        text('### 02 · Tempo por pergunta'), ui.ActionRow(time_menu),
        divider(),
        ui.ActionRow(ActionButton('start', callback, label='Começar aventura', emoji='⚔️', style=discord.ButtonStyle.success),
                     ActionButton('stop', callback, label='Fechar painel', emoji='✖️')),
        text(f'-# Anfitrião: {safe_name(session.host.display_name)} · todos respondem no chat.\n'
             '-# O painel fecha após 2 minutos sem iniciar.'),
        header=[*artwork(0), text(f'{BRAND}\n# Anime Adventures Quiz\nDos primeiros mundos às primeiras unidades.')],
        footer=[utilities(callback)],
    )


def clock_label(session, remaining):
    remaining = max(0, remaining)
    filled = max(0, min(12, math.ceil(remaining / session.question_time * 12)))
    bar = f'`{"▰" * filled}{"▱" * (12-filled)}` **{math.ceil(remaining)}s**'
    if session.is_paused:
        return f'### ⏸️ Tempo congelado\n{bar}\n-# Retomar continua esta pergunta com o mesmo tempo restante.'
    urgency = 'Últimos segundos' if remaining <= 10 else 'Tempo para responder'
    return f'### ⏳ {urgency}\n{bar} · encerra <t:{int(session.ends_at.timestamp())}:R>'


def question_panel(session, callback, remaining):
    question = session.current_question
    icon = CATEGORY_ICONS.get(question.category, '✦')
    badge = f' · ✦ **{RARITY_LABELS[question.rarity]}**' if question.rarity else ''
    paused = ' · EM PAUSA' if session.is_paused else ''
    panel = Panel(
        *illustrated(f'## {question.prompt}', media.for_question(question)),
        text(f'-# Responda no chat · primeiro acerto vale +1 ponto{badge}'),
        color=RARITY_COLORS.get(question.rarity, BRAND_COLOR),
        header=[text(f'{BRAND}\n### {icon} {question.category} · Pergunta {session.question_number:02d}{paused}')],
    )
    panel.clock_text = text(clock_label(session, remaining))
    panel.add_item(ui.Container(panel.clock_text, session_controls(session, callback), accent_color=GOLD if session.is_paused else BRAND_COLOR))
    panel.add_item(utilities(callback))
    if session.stop_requested:
        panel.add_item(text('-# Esta é a última pergunta. O tempo e o ponto continuam valendo.'))
    return panel


def closed_question_panel(session):
    return Panel(
        text(f'{CATEGORY_ICONS.get(session.current_question.category, "✦")} **Pergunta {session.question_number:02d} encerrada**'),
        text(session.current_question.prompt),
        text('-# Confira a resposta e o resultado abaixo.'),
        color=RARITY_COLORS.get(session.current_question.rarity, BRAND_COLOR),
    )


def standings(session):
    entries = sorted(session.session_scores.values(), key=lambda row: (-row['points'], row['first']))[:5]
    medals = ['🥇', '🥈', '🥉', '④', '⑤']
    return '\n'.join(f"{medals[i]} **{safe_name(row['name'])}** — **{row['points']}** {'ponto' if row['points'] == 1 else 'pontos'}" for i, row in enumerate(entries)) or 'O primeiro ponto ainda está em jogo.'


def result_panel(session, winner, total_points, continuing, callback):
    question = session.current_question
    if winner:
        header = f'## ✨ Resposta certa!\n**{safe_name(winner.display_name)}** chegou primeiro. **+1 ponto!**'
        total = f'💎 Total acumulado: **{total_points} pontos**' if total_points is not None else '⚠️ +1 nesta sessão. O total acumulado não pôde ser salvo agora.'
    else:
        header = '## ⌛ O tempo acabou\nNinguém acertou esta pergunta a tempo.'
        total = ''
    children = [*illustrated(f'### {question.answer}\n{question.explanation}', media.for_question(question, revealed=True))]
    if total:
        children.append(text(total))
    children.extend([divider(), text(f'### 🏆 Placar da sessão\n{standings(session)}')])
    if continuing:
        if session.is_paused:
            children.append(text('### ⏸️ Aventura em pausa\nIntervalo congelado. Retomar preserva o tempo que faltava.'))
        else:
            children.append(text(f'### Próxima pergunta <t:{int(session.next_at.timestamp())}:R>\n-# Um intervalo de {session.between_questions:g}s antes do próximo desafio.'))
        children.extend([utilities(callback), session_controls(session, callback)])
    else:
        reason = 'Encerrada pelo anfitrião ou pela moderação.' if session.stop_requested else 'Sem tentativas nesta pergunta, a aventura terminou automaticamente.'
        children.extend([text(f'### ✦ Fim da aventura\n{reason}\n**{session.question_number} perguntas** · **{session.correct_count} acertos**'),
                         ui.ActionRow(ActionButton('replay', callback, label='Jogar novamente', emoji='⚔️', style=discord.ButtonStyle.success),
                                      ActionButton('scores', callback, label='Meus pontos', emoji='💎'))])
    children.append(ui.ActionRow(ui.Button(label='Ver esta resposta na wiki', emoji='📚', url=session.pack.sources[question.sources[0]]['url'])))
    return Panel(*children, color=SUCCESS if winner else GOLD,
                 header=[*(artwork(1) if not continuing else []), text(f'{BRAND}\n{header}')])


def ended_panel(session, reason, callback):
    return Panel(
        text(f'{BRAND}\n## ✦ Aventura encerrada\n{reason}'),
        text(f'**{session.question_number} perguntas** · **{session.correct_count} acertos**'),
        divider(), text(f'### 🏆 Placar da sessão\n{standings(session)}'),
        ui.ActionRow(ActionButton('replay', callback, label='Jogar novamente', emoji='⚔️', style=discord.ButtonStyle.success),
                     ActionButton('scores', callback, label='Meus pontos', emoji='💎')),
        color=GOLD,
        header=artwork(1),
    )


def help_panel():
    return Panel(
        text(f'{BRAND}\n## 📖 Seu guia de aventura'), divider(),
        text('### 1 · Entre no desafio\nUse **/adventures** e toque em **Começar aventura**. O anfitrião pode escolher os assuntos e o tempo antes de começar.'),
        text('### 2 · Responda no chat\nNão precisa entrar em equipe nem escolher alternativas. **A primeira resposta correta vale 1 ponto.** Você pode jogar sozinho ou com todo o canal.'),
        text('### 3 · Use o nome certo\nNas perguntas de personagem, valem os nomes documentados do anime e do jogo. Maiúsculas, acentos e pontuação são ignorados; erros de digitação não são corrigidos. Evoluções pedem o nome da forma evoluída.'),
        text('### 4 · Continue a aventura\nUma tentativa errada também mantém o jogo seguindo. Sem tentativas em uma pergunta, a sessão termina. Consultar ajuda ou placar não conta como tentativa.'),
        text('### ⏸️ Pausa de verdade\nPausar congela o relógio imediatamente e bloqueia respostas. Retomar continua a mesma pergunta com o tempo restante. Só o anfitrião e a moderação controlam pausa e fim. Encerrar durante uma pergunta ativa aguarda seu desfecho; em pausa, encerra na hora.'),
        text('-# Conteúdo do Release · fontes disponíveis após cada resposta · totais acumulados dependem da persistência do serviço.'),
    )


def score_panel(session, user, total):
    personal = f'**{total} pontos acumulados**' if total is not None else 'O total acumulado está indisponível no momento.'
    current = session.session_scores.get(user.id, {}).get('points', 0) if session else None
    session_line = f'\n**{current} pontos nesta sessão**' if current is not None else ''
    children = [text(f'{BRAND}\n## 💎 Seus pontos\n**{safe_name(user.display_name)}**\n{personal}{session_line}')]
    if session:
        children.extend([divider(), text(f'### 🏆 Placar da sessão\n{standings(session)}')])
    children.append(text('-# Esta consulta aparece apenas para você e não interrompe o relógio.'))
    return Panel(*children)


class PersistentControls(ui.View):
    """Fallback routing lets old cards offer help, scores and replay after a restart."""
    def __init__(self, callback):
        super().__init__(timeout=None)
        for index, action in enumerate(['start', 'pause', 'resume', 'stop', 'replay', 'scores', 'help']):
            button = ActionButton(action, callback, label=action)
            button.row = index // 5
            self.add_item(button)
        self.add_item(ChoiceSelect('category', callback, [discord.SelectOption(label='Aventura completa', value='all')], 'Assuntos'))
        self.add_item(ChoiceSelect('time', callback, [discord.SelectOption(label='45 segundos', value='45')], 'Tempo'))
