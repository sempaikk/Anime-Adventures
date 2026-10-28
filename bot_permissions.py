"""Capabilities, not role names: moderation stays separate from configuration."""


def can_moderate(i):
    p = i.permissions
    return bool(i.guild_id and any(getattr(p, key, False) for key in
        ('manage_guild', 'administrator', 'moderate_members', 'manage_messages')))


def require_moderator(i):
    if not can_moderate(i):
        raise ValueError('You need Moderate Members or Manage Messages to moderate this server\'s global chat.')
