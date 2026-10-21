"""Short private error responses without exposing traces or internal details."""

import logging

import discord
from discord import app_commands

log = logging.getLogger('adventures.interactions')


async def respond_to_error(interaction, error):
    original = getattr(error, 'original', error)
    if isinstance(original, discord.Forbidden):
        message = ('Não consegui enviar ou atualizar o painel. Confira minhas permissões de '
                   '**Ver canal**, **Enviar mensagens** e **Inserir links**, depois tente **/adventures** de novo.')
    elif isinstance(original, app_commands.NoPrivateMessage):
        message = 'Use **/adventures** em um canal de texto do servidor.'
    elif isinstance(original, discord.HTTPException):
        message = 'O Discord não conseguiu concluir essa ação agora. Tente novamente pelo painel mais recente.'
    else:
        message = 'Não consegui concluir essa ação. Tente pelo painel mais recente ou use **/adventures** de novo.'
    log.error('Falha de interação: %s', type(original).__name__, exc_info=error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        # An expired interaction or Discord outage cannot be repaired by another reply.
        log.warning('A resposta privada ao erro também não pôde ser entregue.')
