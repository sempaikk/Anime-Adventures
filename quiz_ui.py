"""Native Discord Components V2 screens and controls, shared by desktop and mobile."""

from __future__ import annotations

import logging
import math
import unicodedata

import discord
from discord import ui

import quiz_media as media
import quiz_icons as icons

BRAND_COLOR = 0x8664E8
GOLD = 0xF4C95D
SUCCESS = 0x50D6A0
RARITY_COLORS = {'Rare': 0x4CA9F5, 'Epic': 0xAE70ED, 'Legendary': GOLD, 'Mythic': 0xF05C75}
RARITY_LABELS = {'Rare': 'Rara', 'Epic': 'Épica', 'Legendary': 'Lendária', 'Mythic': 'Mítica'}
CATEGORY_ICONS = {
    'Unidades': 'units', 'Raridades': 'units', 'Evoluções': 'evolution', 'Mundos': 'summon',
    'Chefes': 'damage', 'Atos': 'summon', 'Comida e XP': 'items', 'Traits': 'traits',
    'Summon': 'summon', 'Economia': 'items', 'Modos': 'power', 'Missões': 'items',
    'Loja e códigos': 'items', 'Upgrades': 'range',
}
GROUPS = {
    'all': ('Tudo junto', None, 'Todos os assuntos disponíveis'),
    'characters': ('Personagens', {'Unidades', 'Raridades', 'Evoluções', 'Upgrades'}, 'Identidade, raridades, evoluções e upgrades'),
    'worlds': ('Mundos e chefes', {'Mundos', 'Chefes', 'Atos'}, 'Explore os quatro mundos do lançamento'),
    'systems': ('Sistemas do jogo', {'Comida e XP', 'Traits', 'Summon', 'Economia', 'Modos', 'Missões', 'Loja e códigos'}, 'Comida, XP, traits, summon, missões e economia'),
}
log = logging.getLogger('adventures.ui')


def safe_name(value):
    # Directional controls can visually reorder a score row; preserve normal Unicode names.
    value = ''.join(c for c in value if c not in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069')
    value = ''.join(' ' if unicodedata.category(c) == 'Cc' else c for c in value).strip()
    value = ' '.join(value.split())
    return discord.utils.escape_markdown(discord.utils.escape_mentions(value[:80]))


def text(value):
    return ui.TextDisplay(value)


def quantity(value, singular, plural=None):
    return f'{value} {singular if value == 1 else plural or singular + "s"}'


def session_summary(session):
    return f'**{quantity(session.question_number, "pergunta")}** · **{quantity(session.correct_count, "acerto")}**'


def round_label(session):
    return f'{session.round_limit} perguntas' if session.round_limit else 'Partida contínua'


def question_number(session):
    return f'{session.question_number:02d}/{session.round_limit}' if session.round_limit else f'{session.question_number:02d}'


def question_icon(question):
    # A reroll-item icon in this header would directly answer the question.
    key = 'items' if question.id == 'trait:item' else CATEGORY_ICONS.get(question.category)
    return icons.markup(key)


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
        if getattr(self, 'next_text', None):
            self.next_text.content = '### Rodada concluída\n-# Acompanhe a próxima pergunta abaixo.'
        for item in self.walk_children():
            if isinstance(item, (ui.Button, ui.Select)) and not getattr(item, 'url', None):
                item.disabled = True
        self.stop()

    async def on_error(self, interaction, error, item):
        log.error('Erro no controle %s: %s', getattr(item, 'custom_id', '?'), type(error).__name__, exc_info=error)
        message = 'Não deu para atualizar o painel agora. Tente clicar de novo no painel mais recente.'
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=True)
        else:
            await interaction.followup.send(message, ephemeral=True)


def utilities(callback):
    return ui.ActionRow(
        ActionButton('scores', callback, label='Placar', emoji=icons.component('rank')),
        ActionButton('help', callback, label='Como jogar'),
    )


def session_controls(session, callback):
    paused = session.is_paused
    return ui.ActionRow(
        ActionButton('resume' if paused else 'pause', callback,
                     label='Retomar' if paused else 'Pausar',
                     style=discord.ButtonStyle.success if paused else discord.ButtonStyle.secondary),
        ActionButton('stop', callback, label='Fim marcado' if session.stop_requested else 'Encerrar',
                     style=discord.ButtonStyle.danger, disabled=session.stop_requested),
    )


def artwork(index=0):
    asset = media.banner(index)
    return [ui.MediaGallery(discord.MediaGalleryItem(asset['url'], description=asset['alt']))] if asset else []


def illustrated(content, asset, *, focus=False):
    large_portrait = focus and asset and min(asset.get('width', 0), asset.get('height', 0)) >= 200
    if asset and asset['display'] == 'portrait' and not large_portrait:
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
        discord.SelectOption(label=label, value=key, description=description, default=key == session.group,
                             emoji=icons.component({'all': 'summon', 'characters': 'units', 'worlds': 'damage', 'systems': 'items'}[key]))
        for key, (label, _, description) in GROUPS.items()
    ], 'Escolha os assuntos')
    time_menu = ChoiceSelect('time', callback, [
        discord.SelectOption(label=f'{seconds} segundos', value=str(seconds), description=description, default=seconds == session.question_time)
        for seconds, description in [(30, 'Partida rápida'), (45, 'Tempo padrão · recomendado'), (60, 'Mais tempo para pensar')]
    ], 'Escolha o tempo de resposta')
    round_menu = ChoiceSelect('rounds', callback, [
        discord.SelectOption(label=f'{n} perguntas', value=str(n), default=session.round_limit == n)
        for n in (10, 20, 30)
    ] + [discord.SelectOption(label='Partida contínua', value='continuous',
                             description='Continue até encerrar ou ficar sem participação', default=session.round_limit is None)],
                              'Escolha a duração da partida')
    return Panel(
        *illustrated('## Preparar partida\nEscolha como jogar. Todo mundo no canal pode participar.', icons.asset('items')),
        text(f'**{group}** · **{round_label(session)}**\n**{session.question_time:g}s** por pergunta · primeiro acerto vale **1 ponto**\n-# {count:,} perguntas disponíveis em {categories} categorias'.replace(',', '.')),
        divider(), text(f'### {icons.markup("units")}01 · Assuntos'), ui.ActionRow(category_menu),
        text(f'### {icons.markup("clock")}02 · Tempo por pergunta'), ui.ActionRow(time_menu),
        text(f'### {icons.markup("rank")}03 · Duração da partida'), ui.ActionRow(round_menu),
        divider(),
        ui.ActionRow(ActionButton('start', callback, label='Começar', emoji=icons.component('summon'), style=discord.ButtonStyle.success),
                     ActionButton('stop', callback, label='Fechar painel')),
        text(f'-# Criado por {safe_name(session.host.display_name)} · respostas no chat ou nos botões, conforme a pergunta.\n'
             '-# Cada pergunta soma no total global uma vez a cada 24h. O painel fecha após 2 minutos sem iniciar.'),
        header=artwork(0),
        footer=[utilities(callback)],
    )


def clock_label(session, remaining):
    remaining = max(0, remaining)
    filled = max(0, min(12, math.ceil(remaining / session.question_time * 12)))
    bar = f'`{"▰" * filled}{"▱" * (12-filled)}` **{math.ceil(remaining)}s**'
    if session.is_paused:
        return f'### {icons.markup("clock")}Tempo congelado\n{bar}\n-# Ao retomar, o relógio continua de onde parou. Pausa máxima de 10 minutos.'
    urgency = 'Últimos segundos' if remaining <= 10 else 'Tempo para responder'
    return f'### {icons.markup("clock")}{urgency}\n{bar} · encerra <t:{int(session.ends_at.timestamp())}:R>'


def question_panel(session, callback, remaining):
    question = session.current_question
    icon = question_icon(question)
    badge = f' · **{RARITY_LABELS[question.rarity]}**' if question.rarity else ''
    paused = ' · EM PAUSA' if session.is_paused else ''
    asset = media.for_question(question)
    identification = question.id.startswith('unit:')
    identity_note = '\n-# Reconheça a unidade pela imagem. Vale nome atual, antigo ou do anime.' if identification else ''
    instruction = ('Escolha abaixo · 1 tentativa por pessoa · primeiro acerto vale +1 ponto' if question.options else
                   f'Responda no chat · até {session.chat_attempt_limit} tentativas por pessoa · primeiro acerto vale +1 ponto')
    panel = Panel(
        *illustrated(f'## {question.prompt}', asset, focus=identification),
        text(f'-# {instruction}{badge}{identity_note}'),
        color=RARITY_COLORS.get(question.rarity, BRAND_COLOR),
        header=[text(f'### {icon}{question.category} · Pergunta {question_number(session)}{paused}')],
    )
    if question.options:
        for index, label in enumerate(session.choice_order or question.options):
            panel.card.add_item(ui.ActionRow(ActionButton(f'answer:{index}', callback, label=f'{"ABC"[index]} · {label}',
                                disabled=session.is_paused)))
    panel.clock_text = text(clock_label(session, remaining))
    panel.add_item(ui.Container(panel.clock_text, session_controls(session, callback), accent_color=GOLD if session.is_paused else BRAND_COLOR))
    panel.add_item(utilities(callback))
    if session.stop_requested:
        panel.add_item(text('-# Esta é a última pergunta. O tempo e o ponto continuam valendo.'))
    return panel


def closed_question_panel(session):
    return Panel(
        text(f'{question_icon(session.current_question)}**Pergunta {question_number(session)} encerrada**'),
        text(session.current_question.prompt),
        text('-# A resposta e o placar estão logo abaixo.'),
        color=RARITY_COLORS.get(session.current_question.rarity, BRAND_COLOR),
    )


def standings(session):
    entries = sorted(session.session_scores.values(), key=lambda row: (-row['points'], row['first']))[:5]
    return '\n'.join(f"{i + 1}. **{safe_name(row['name'])}** · **{quantity(row['points'], 'ponto')}**" for i, row in enumerate(entries)) or 'O primeiro ponto ainda está em jogo.'


def match_leaders(session):
    if not session.session_scores:
        return ''
    best = max(row['points'] for row in session.session_scores.values())
    leaders = [row for row in session.session_scores.values() if row['points'] == best]
    names = ', '.join('**' + safe_name(row['name']) + '**' for row in leaders[:3])
    extra = f' e mais {len(leaders) - 3}' if len(leaders) > 3 else ''
    return (f'Empate na liderança: {names}{extra} · **{quantity(best, "ponto")}** cada.' if len(leaders) > 1 else
            f'Liderou a partida: {names} · **{quantity(best, "ponto")}**.')


def result_panel(session, winner, total_points, continuing, callback):
    question = session.current_question
    if winner:
        header = f'## {icons.markup("power")}Resposta certa!\n**{safe_name(winner.display_name)}** chegou primeiro. **+1 ponto!**'
        total = f'Total acumulado: **{quantity(total_points, "ponto")}**' if total_points is not None else 'Você ganhou +1 nesta partida, mas não deu para salvar no total agora.'
        if total_points is not None and session.global_credited is False:
            total += '\n-# Esta pergunta já contou no seu total nas últimas 24h. O ponto valeu no placar desta partida.'
    else:
        header = f'## {icons.markup("clock")}Tempo esgotado\nEssa passou! Confira a resposta abaixo.'
        total = ''
    children = [*illustrated(f'### {question.answer}\n{question.explanation}', media.for_question(question, revealed=True))]
    if total:
        children.append(text(total))
    children.extend([divider(), text(f'### {icons.markup("rank")}Placar da partida\n{standings(session)}')])
    next_text = None
    if continuing:
        if session.is_paused:
            next_text = text(f'### {icons.markup("clock")}Partida pausada\nIntervalo congelado. Ao retomar, continua de onde parou. Pausa máxima de 10 minutos.')
        else:
            next_text = text(f'### Próxima pergunta <t:{int(session.next_at.timestamp())}:R>\n-# {session.between_questions:g}s para conferir a resposta e se preparar.')
        children.append(next_text)
        children.extend([utilities(callback), session_controls(session, callback)])
    else:
        reason = session.finish_reason()
        children.extend([text(f'### Fim de jogo\n{reason}\n{session_summary(session)}\n{match_leaders(session)}'),
                         ui.ActionRow(ActionButton('replay', callback, label='Jogar de novo', emoji=icons.component('summon'), style=discord.ButtonStyle.success),
                                      ActionButton('scores', callback, label='Meus pontos', emoji=icons.component('rank')))])
    children.append(ui.ActionRow(ui.Button(label='Conferir na wiki', url=session.pack.sources[question.sources[0]]['url'])))
    panel = Panel(*children, color=SUCCESS if winner else GOLD,
                  header=[*(artwork(1) if not continuing else []), text(header)])
    panel.next_text = next_text
    return panel


def ended_panel(session, reason, callback):
    return Panel(
        text(f'## Fim de jogo\n{reason}'),
        text(session_summary(session) + '\n' + match_leaders(session)),
        divider(), text(f'### {icons.markup("rank")}Placar da partida\n{standings(session)}'),
        ui.ActionRow(ActionButton('replay', callback, label='Jogar de novo', emoji=icons.component('summon'), style=discord.ButtonStyle.success),
                     ActionButton('scores', callback, label='Meus pontos', emoji=icons.component('rank'))),
        color=GOLD,
        header=artwork(1),
    )


def help_panel():
    return Panel(
        *illustrated('## Como jogar', icons.asset('items')), divider(),
        text('### 1 · Comece uma partida\nUse **/adventures**, escolha os assuntos, o tempo e 10, 20 ou 30 perguntas. Se quiser jogar sem limite de rodadas, escolha **Partida contínua**. Toque em **Começar**. Só quem abriu o painel ajusta essas opções.'),
        text('### 2 · Veja como responder\n**O primeiro acerto vale 1 ponto.** Algumas perguntas pedem resposta no chat, outras mostram uma imagem ou três alternativas. No chat, cada pessoa pode enviar **até três respostas diferentes** por pergunta; repetir a mesma não gasta outra tentativa. Nas alternativas, vale **uma tentativa** por pessoa. Quem acertar primeiro leva o ponto.'),
        text('### 3 · Qual nome vale?\nAceitamos os nomes cadastrados do jogo (atuais e antigos) e do anime. Maiúsculas e acentos não fazem diferença. Confira a digitação: nomes parecidos não contam. Se a pergunta pedir uma evolução, responda a forma evoluída.'),
        text('### 4 · Mantenha a partida rolando\nTentou e errou? Tudo bem, a partida continua. Ela termina ao chegar ao total escolhido, ao encerrar pelo botão ou na primeira rodada sem tentativa. Abrir ajuda ou placar não conta como resposta.'),
        text('### 5 · Pontuação\nTodo primeiro acerto vale **1 ponto na partida**. No **total global**, a mesma pergunta soma um ponto por pessoa a cada **24 horas**, mesmo mudando de canal ou abrindo outra partida.'),
        text('### Precisa de uma pausa?\nQuem abriu a partida e a moderação podem pausar e encerrar. Pausar trava o relógio e as respostas; retomar continua do mesmo ponto. Uma pausa de **10 minutos** encerra a partida. Ao encerrar com uma pergunta ativa, ela termina primeiro. Com a partida pausada, encerra na hora.'),
        text('-# A ajuda e seus pontos aparecem só para você. A fonte de cada resposta fica no botão da wiki.'),
    )


def score_panel(session, user, total):
    personal = f'**Total: {quantity(total, "ponto")}**' if total is not None else 'Não deu para consultar seu total agora. Tente de novo daqui a pouco.'
    current = session.session_scores.get(user.id, {}).get('points', 0) if session else None
    session_line = f'\n**Nesta partida: {quantity(current, "ponto")}**' if current is not None else ''
    children = [*illustrated(f'## Seus pontos\n**{safe_name(user.display_name)}**\n{personal}{session_line}', icons.asset('rank'))]
    if session:
        children.extend([divider(), text(f'### {icons.markup("rank")}Placar da partida\n{standings(session)}')])
    children.append(text('-# No total global, cada pergunta conta uma vez a cada 24h.\n-# Só você vê essa consulta. O relógio da partida continua rodando.'))
    return Panel(*children)


class PersistentControls(ui.View):
    """Fallback routing lets old cards offer help, scores and replay after a restart."""
    def __init__(self, callback):
        super().__init__(timeout=None)
        for index, action in enumerate(['start', 'pause', 'resume', 'stop', 'replay', 'scores', 'help', 'answer:0', 'answer:1', 'answer:2']):
            button = ActionButton(action, callback, label=action)
            button.row = index // 5
            self.add_item(button)
        self.add_item(ChoiceSelect('category', callback, [discord.SelectOption(label='Tudo junto', value='all')], 'Assuntos'))
        self.add_item(ChoiceSelect('time', callback, [discord.SelectOption(label='45 segundos', value='45')], 'Tempo'))
        self.add_item(ChoiceSelect('rounds', callback, [discord.SelectOption(label='10 perguntas', value='10')], 'Duração'))
