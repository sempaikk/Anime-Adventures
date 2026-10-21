"""Authorization for private review, reports, host transfer and recovery controls."""

import re

import discord

import adventure_views as views

FEATURES = {'manage','review','report','claim','resume_saved','status','reports','transfer_target'}


def same_scope(state,interaction):
    return (state and str(state['guild_id'])==str(getattr(interaction.guild,'id',None))
            and str(state['channel_id'])==str(interaction.channel_id))


async def private_view(interaction,view,*,update=False):
    private = bool(getattr(getattr(interaction.message,'flags',None),'ephemeral',False))
    if update and private:
        await interaction.response.edit_message(view=view)
    else:
        await interaction.response.send_message(view=view,ephemeral=True)


async def handle_feature(interaction,action,value,*,session,client,callback,is_moderator):
    kind = action.split(':',1)[0]
    if kind not in FEATURES and kind not in ('review_page','report_page','report_done','claim_game'):
        return False
    async def message(content):
        if hasattr(interaction.response,'is_done') and interaction.response.is_done():
            await interaction.followup.send(content,ephemeral=True)
        else:
            await interaction.response.send_message(content,ephemeral=True)
    if not getattr(interaction,'guild',None) or not getattr(interaction,'channel',None):
        await message('Use os controles no canal do servidor onde a partida aconteceu.')
        return True
    moderator = is_moderator(interaction.user)
    owner = bool(session and interaction.user.id==session.host.id)
    repo = client.adventures
    guild_id = getattr(interaction.guild,'id',None)

    if kind == 'status':
        await private_view(interaction,views.status_panel(client.health,session=session,moderator=moderator))
        return True
    if kind in ('reports','report_page','report_done'):
        if not moderator:
            await message('Só a moderação pode revisar os avisos deste servidor.')
            return True
        if repo is None:
            await message('A fila de revisão não está disponível agora.')
            return True
        page = 0
        if kind != 'reports':
            try:
                _,ref,number = action.split(':')
                page = int(number)
                if kind=='report_page' and str(guild_id)!=ref:
                    raise ValueError
                if kind=='report_done':
                    repo.review_report(int(ref),guild_id,interaction.user.id)
            except (ValueError,TypeError):
                await message('Esse controle de revisão não é válido neste servidor.')
                return True
        await private_view(interaction,views.reports_panel(repo.reports(guild_id,page),guild_id,client.pack),update=kind!='reports')
        return True

    if kind in ('review','review_page','report'):
        state, context, page = None,None,0
        if kind=='review_page':
            try:
                _,sid,number = action.split(':')
                if not re.fullmatch('[a-f0-9]{32}',sid):
                    raise ValueError
                page = int(number)
                state = repo.get(sid) if repo else None
            except (ValueError,TypeError):
                state = None
        else:
            context = repo.context(interaction.message.id) if repo and interaction.message else None
            state = context['session'] if context else None
            if state is None and kind=='review' and session and session.control_message and interaction.message and session.control_message.id==interaction.message.id:
                state = session.snapshot()
        if not same_scope(state,interaction):
            await message('A revisão desse painel expirou ou pertence a outro canal.')
            return True
        if kind=='report':
            if not context or not context['resolved'] or not context['question_id']:
                await message('Espere a resposta ser revelada para sinalizar essa pergunta.')
                return True
            await interaction.response.send_modal(views.ReportModal(repo,interaction.message.id,guild_id,interaction.channel_id,interaction.user.id))
        else:
            await private_view(interaction,views.review_panel(state,interaction.user,client.pack,callback,page),update=kind=='review_page')
        return True

    if not session or not session.running:
        await message('Essa partida já foi encerrada. Use **/adventures** para abrir outra.')
        return True
    if kind=='manage':
        if not interaction.message or not session.control_message or session.control_message.id!=interaction.message.id:
            await message('Abra os controles pelo painel mais recente da partida.')
            return True
        await private_view(interaction,views.manage_panel(session,interaction.user,callback,moderator=moderator))
        return True
    if kind=='transfer_target':
        if not isinstance(value,tuple) or len(value)!=2 or value[0]!=session.session_id or not (owner or moderator):
            await message('Só o anfitrião atual e a moderação podem passar o controle desta partida.')
            return True
        await interaction.response.defer(ephemeral=True)
        try:
            target = await interaction.guild.fetch_member(int(value[1]))
        except (ValueError,discord.NotFound):
            await message('Escolha uma pessoa que ainda esteja neste servidor.')
            return True
        if (target.bot or not session.running or str(getattr(getattr(target,'guild',None),'id',None))!=str(guild_id)
                or (not moderator and interaction.user.id!=session.host.id)):
            await message('O controle precisa ir para uma pessoa, e quem envia ainda precisa ser o anfitrião.')
            return True
        session.host,session.host_missing = target,False
        session.checkpoint()
        await message('Controle transferido. O novo anfitrião já pode pausar, retomar e encerrar.')
        await session.refresh_controls()
        return True
    if kind in ('claim','claim_game'):
        if kind=='claim_game' and action.split(':')[1]!=session.session_id:
            await message('Esse controle pertence a outra partida.')
            return True
        if kind=='claim' and (not interaction.message or not session.control_message or session.control_message.id!=interaction.message.id):
            await message('Use o painel mais recente para assumir o controle.')
            return True
        if not session.host_missing or not (moderator or interaction.user.id in session.performance):
            await message('Só quem já participou ou a moderação pode assumir quando o anfitrião sai do servidor.')
            return True
        expected_host = session.host.id
        await interaction.response.defer(ephemeral=True)
        try:
            await interaction.guild.fetch_member(expected_host)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            await message('Não consegui confirmar a saída do anfitrião agora. Tente novamente em instantes.')
            return True
        else:
            if session.host.id!=expected_host or not session.host_missing:
                await message('O controle já foi atualizado. Confira o painel mais recente.')
                return True
            session.host_missing = False
            session.checkpoint()
            await message('O anfitrião voltou ao servidor. O controle continua com ele.')
            return True
        if not session.running or not session.host_missing or session.host.id!=expected_host:
            await message('Outra pessoa já assumiu o controle. Confira o painel mais recente.')
            return True
        session.host,session.host_missing = interaction.user,False
        session.checkpoint()
        await message('Você assumiu o controle da partida.')
        await session.refresh_controls()
        return True
    if kind=='resume_saved':
        if (session.phase!='recovery' or not (owner or moderator) or not interaction.message
                or not session.control_message or session.control_message.id!=interaction.message.id):
            await message('Só o anfitrião e a moderação podem retomar pelo painel de recuperação atual.')
            return True
        if client.connection_lost:
            await message('Aguarde a conexão com o Discord voltar antes de retomar.')
            return True
        if session.stop_requested or (session.round_limit and session.question_number>=session.round_limit):
            await interaction.response.defer()
            await session.stop_now('A partida salva já foi concluída. Seus pontos foram preservados.')
            return True
        session.launch()
        await interaction.response.defer()
        return True
    return True
