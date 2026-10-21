"""Secondary native screens keep the public match compact and the tools private."""

import math
import time

import discord
from discord import ui

import quiz_icons as icons
import quiz_media as media
import quiz_ui as screen
from difficulty import LABELS, FORMATS
from interaction_errors import respond_to_error


class DynamicControls(ui.DynamicItem[ui.Button],template=r'aa:(?P<kind>review_page|report_page|report_done|claim_game):(?P<ref>[a-f0-9]{1,32}):(?P<page>[0-9]{1,4})'):
    dispatch = None

    def __init__(self, action, *, label='Abrir', disabled=False, item=None):
        self.action = action
        super().__init__(item or ui.Button(label=label,custom_id='aa:'+action,disabled=disabled))

    @classmethod
    async def from_custom_id(cls,interaction,item,match):
        return cls(f'{match["kind"]}:{match["ref"]}:{match["page"]}',item=item)

    async def callback(self,interaction):
        try:
            await type(self).dispatch(interaction,self.action)
        except Exception as error:
            await respond_to_error(interaction,error)


class DynamicTransfer(ui.DynamicItem[ui.UserSelect],template=r'aa:transfer:(?P<sid>[a-f0-9]{32})'):
    dispatch = None

    def __init__(self,sid,item=None):
        self.session_id = sid
        super().__init__(item or ui.UserSelect(custom_id=f'aa:transfer:{sid}',placeholder='Escolha o novo anfitrião',min_values=1,max_values=1))

    @classmethod
    async def from_custom_id(cls,interaction,item,match):
        return cls(match['sid'],item)

    async def callback(self,interaction):
        values = (interaction.data or {}).get('values',[])
        try:
            await type(self).dispatch(interaction,'transfer_target',(self.session_id,values[0] if len(values)==1 else ''))
        except Exception as error:
            await respond_to_error(interaction,error)


class ReportModal(ui.Modal,title='Sinalizar pergunta'):
    reason = ui.TextInput(label='O que precisa ser corrigido?',placeholder='Explique o problema com a resposta, o texto ou a imagem.',
                          style=discord.TextStyle.paragraph,min_length=5,max_length=400)

    def __init__(self,repository,message_id,guild_id,channel_id,user_id):
        super().__init__(timeout=300)
        self.repository,self.message_id = repository,message_id
        self.guild_id,self.channel_id,self.user_id = guild_id,channel_id,user_id

    async def on_submit(self,interaction):
        if (interaction.user.id != self.user_id or interaction.guild_id != self.guild_id
                or interaction.channel_id != self.channel_id):
            await interaction.response.send_message('Abra o formulário pelo painel da pergunta.',ephemeral=True)
            return
        try:
            self.repository.report(self.message_id,self.guild_id,self.channel_id,self.user_id,str(self.reason))
            message = 'Aviso salvo na fila de revisão deste servidor. Obrigado por apontar o problema!'
        except ValueError as error:
            message = str(error)
        await interaction.response.send_message(message,ephemeral=True)

    async def on_error(self,interaction,error):
        await respond_to_error(interaction,error)


class PersistentExtras(ui.View):
    def __init__(self,callback):
        super().__init__(timeout=None)
        for index,action in enumerate(['advanced','manage','review','report','claim','resume_saved','status','reports']):
            self.add_item(screen.ActionButton(action,callback,label=action))
        self.add_item(screen.ChoiceSelect('difficulty',callback,[discord.SelectOption(label='Todos',value='all')],'Nível'))
        self.add_item(screen.ChoiceSelect('format',callback,[discord.SelectOption(label='Misto',value='mixed')],'Formato'))

    async def on_error(self,interaction,error,item):
        await respond_to_error(interaction,error)


def recovery_panel(session,callback,*,restarting=False):
    reason = ('O bot está reiniciando. A partida foi salva para continuar quando ele voltar.' if restarting else
              'Placar e opções foram recuperados. Retome quando o pessoal estiver pronto.')
    return screen.Panel(
        *screen.illustrated('## Partida salva\n'+reason,icons.asset('items')),
        screen.text(f'**{screen.GROUPS[session.group][0]}** · **{screen.round_label(session)}**\n'
                    f'{LABELS[session.difficulty]} · {FORMATS[session.answer_mode]} · {session.question_time:g}s\n'
                    f'{screen.session_summary(session)}'),screen.divider(),
        screen.text(f'### Placar da partida\n{screen.standings(session)}'),
        screen.text('-# Uma rodada interrompida sem acerto é anulada. Pontos já gravados não contam duas vezes.\n'
                    '-# O anfitrião e a moderação podem retomar. O painel expira em 10 minutos.'),
        ui.ActionRow(screen.ActionButton('resume_saved',callback,label='Retomar partida',style=discord.ButtonStyle.success),
                     screen.ActionButton('stop',callback,label='Encerrar'),screen.ActionButton('manage',callback,label='Controles')),
        color=screen.GOLD)


def manage_panel(session,user,callback,*,moderator=False):
    owner = user.id == session.host.id
    children = [*screen.illustrated('## Controles da partida',icons.asset('items')),
                screen.text(f'Anfitrião: **{screen.safe_name(session.host.display_name)}**\n'
                            + ('O anfitrião saiu do servidor.' if session.host_missing else 'As opções da partida continuam no painel público.'))]
    if owner or moderator:
        children += [screen.divider(),screen.text('### Passar o controle\nEscolha alguém deste servidor para cuidar da partida.'),
                     ui.ActionRow(DynamicTransfer(session.session_id))]
    if session.host_missing:
        children += [ui.ActionRow(DynamicControls(f'claim_game:{session.session_id}:0',label='Assumir controle')),
                     screen.text('-# Quem já participou ou faz parte da moderação pode assumir.')]
    children += [screen.divider(),ui.ActionRow(screen.ActionButton('status',callback,label='Estado do bot'))]
    if moderator:
        children[-1].add_item(screen.ActionButton('reports',callback,label='Revisar avisos'))
    return screen.Panel(*children,timeout=300)


def review_panel(state,user,pack,callback,page=0):
    uid = user.id
    entry = state['performance'].get(str(uid),state['performance'].get(uid,{}))
    history = [r for r in state['reviews'] if uid in r['participants']]
    page = max(0,min(page,max(0,(len(history)-1)//3)))
    selected = list(reversed(history))[page*3:page*3+3]
    played, won = entry.get('played',0),entry.get('won',0)
    categories = sorted(entry.get('categories',{}).items(),key=lambda row:(-row[1]['played'],row[0]))
    children = [*screen.illustrated('## Seu desempenho\n**'+screen.safe_name(user.display_name)+'**',icons.asset('rank')),
                screen.text(f'**{screen.quantity(played,"rodada")} com participação** · **{screen.quantity(won,"primeiro acerto","primeiros acertos")}**\n'
                            f'**{round(won/played*100) if played else 0}%** das rodadas disputadas\n'
                            '-# Esse percentual inclui a disputa por velocidade; não mede sozinho seu conhecimento.')]
    if categories:
        children += [screen.divider(),screen.text('### Por assunto\n'+'\n'.join(
            f'**{name}** · {numbers["won"]}/{numbers["played"]} primeiros acertos' for name,numbers in categories))]
    by_id = {q.id:q for q in pack.questions}
    for record in selected:
        question = by_id.get(record['question_id'])
        if not question:
            children += [screen.divider(),screen.text(f'Pergunta {record["number"]}: conteúdo indisponível nesta versão.')]
            continue
        outcome = 'Você chegou primeiro' if record['winner_id']==uid else 'Sem primeiro acerto'
        content = f'### Pergunta {record["number"]} · {outcome}\n{question.prompt[:230]}\n\n**Resposta:** {question.answer[:160]}\n{question.explanation[:200]}'
        children += [screen.divider(),*screen.illustrated(content,media.for_question(question,revealed=True)),
                     ui.ActionRow(ui.Button(label='Conferir a fonte',url=pack.sources[question.sources[0]]['url']))]
    if not selected:
        children.append(screen.text('Suas rodadas concluídas vão aparecer aqui depois que você participar.'))
    children += [screen.divider(),screen.text(f'-# Página {page+1}/{max(1,math.ceil(len(history)/3))} · revisão das últimas 50 rodadas da partida.\n'
                                             '-# Os totais acima incluem toda a partida. Só você vê esta consulta.'),
                 ui.ActionRow(DynamicControls(f'review_page:{state["id"]}:{max(0,page-1)}',label='Anterior',disabled=page==0),
                              DynamicControls(f'review_page:{state["id"]}:{page+1}',label='Próxima',disabled=(page+1)*3>=len(history)))]
    return screen.Panel(*children,timeout=300)


def reports_panel(queue,guild_id,pack):
    children = [screen.text(f'## Avisos de perguntas\n**{screen.quantity(queue["total"],"aviso")} na fila deste servidor**'),
                screen.text('-# Conteúdo enviado por jogadores. Revisar um aviso não altera perguntas nem pontos.')]
    by_id = {q.id:q for q in pack.questions}
    for report in queue['items']:
        question = by_id.get(report['question_id'])
        reason = ''.join(c for c in report['reason'] if unicontrol(c))[:400]
        reason = discord.utils.escape_markdown(discord.utils.escape_mentions(reason))
        prompt = question.prompt[:180] if question else 'Pergunta de uma versão anterior.'
        answer = '\n**Resposta cadastrada:** '+question.answer[:160] if question else ''
        content = f'### Aviso #{report["id"]}\n{prompt}{answer}\n\n**Relato do jogador:**\n{reason}'
        row = ui.ActionRow(DynamicControls(f'report_done:{report["id"]}:0',label='Marcar revisado'))
        if question:
            row.add_item(ui.Button(label='Conferir a fonte',url=pack.sources[question.sources[0]]['url']))
        children += [screen.divider(),*screen.illustrated(content,media.for_question(question,revealed=True) if question else None),row]
    page = queue['page']
    if not queue['total']:
        children += [screen.divider(),screen.text('**Tudo em dia.** Nenhuma pergunta aguardando revisão neste servidor.')]
    else:
        children += [screen.divider(),screen.text(f'-# Página {page+1}/{math.ceil(queue["total"]/3)} · só a moderação vê esta consulta.'),ui.ActionRow(
            DynamicControls(f'report_page:{guild_id}:{max(0,page-1)}',label='Anterior',disabled=page==0),
            DynamicControls(f'report_page:{guild_id}:{page+1}',label='Próxima',disabled=(page+1)*3>=queue['total']))]
    return screen.Panel(*children,timeout=300)


def unicontrol(char):
    return char not in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' and (ord(char)>=32 or char=='\n')


def status_panel(health,*,session=None,moderator=False):
    data = health.status()
    status = ('Em recuperação' if not data['gateway'] or not data['database'] else
              'Em atenção' if data['storage'] in ('warning','critical') or data['backup_error'] else 'Conectado')
    children = [*screen.illustrated('## Estado do bot\n**'+status+'**',icons.asset('power')),
                screen.text(f'**Tempo online:** {data["uptime"]//3600}h {(data["uptime"]%3600)//60}min\n'
                            f'**Pontos:** {"disponíveis" if data["database"] else "consulta indisponível"}')]
    if session and session.persistence_failed:
        children.append(screen.text('**Atenção:** a última cópia da partida não pôde ser salva. A pontuação tem gravação independente.'))
    if moderator:
        backup = f'<t:{int(data["last_backup"])}:R>' if data['last_backup'] else 'ainda sem confirmação'
        storage = {'unknown':'aguardando leitura','ok':'normal','warning':'atenção','critical':'quase cheio'}[data['storage']]
        children += [screen.divider(),screen.text(f'**Backup local:** {backup}\n'
                    f'**Armazenamento:** {storage}\n'
                    + ('A última tentativa de backup falhou; confira os logs.' if data['backup_error'] else ''))]
    children.append(screen.text('-# Esta consulta é privada. O serviço de hospedagem e a rede também podem afetar a disponibilidade.'))
    return screen.Panel(*children,color=screen.SUCCESS if status=='Conectado' else screen.GOLD,timeout=300)
