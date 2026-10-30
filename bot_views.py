"""Private replies and controls bound to the member who opened them."""

import logging
import discord
from bot_ui import payload

log=logging.getLogger("adventures.ui")


def action_error(error):
    if isinstance(error,discord.Forbidden):
        return "Discord denied access. A server administrator needs to check the bot's channel permissions."
    if getattr(error,'status',0)==429:
        return 'Discord is limiting requests. Wait for the automatic retry, then check status before repeating the action.'
    if isinstance(error,OSError):
        return 'Temporary storage or network access is unavailable. The bot owner can check private diagnostics. Check status before trying again.'
    return "The action's result could not be confirmed. Check its status before trying again. The bot owner can check private diagnostics."


async def reply(i, text=None, **kwargs):
    kwargs.setdefault("ephemeral", True)
    kwargs = payload(bot=getattr(i, "client", None), content=text, **kwargs)
    if i.response.is_done():
        return await i.followup.send(**kwargs)
    return await i.response.send_message(**kwargs)


class GuardedView(discord.ui.View):
    async def on_error(self, i, error, item):
        if isinstance(error, ValueError):
            await reply(i, str(error))
        elif isinstance(error, discord.Forbidden):
            await reply(
                i,
                "Discord denied a required permission. Ask an administrator to check the bot's channel access.",
            )
        else:
            log.warning("Interface indisponível: %s", type(error).__name__)
            await reply(
                i,
                action_error(error),
            )


class BoundModal(discord.ui.Modal):
    def bind(self, bot, i):
        self.bot, self.actor, self.guild, self.channel = (
            bot,
            i.user.id,
            i.guild_id,
            i.channel_id,
        )

    async def interaction_check(self, i):
        if (i.user.id, i.guild_id, i.channel_id) != (
            self.actor,
            self.guild,
            self.channel,
        ):
            await reply(i, "Open the form using your own button.")
            return False
        return True

    async def on_error(self, i, error):
        if isinstance(error, ValueError):
            await reply(i, str(error))
        else:
            log.warning("Formulário indisponível: %s", type(error).__name__)
            await reply(
                i,
                action_error(error),
            )
