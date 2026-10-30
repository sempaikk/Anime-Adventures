"""Private game tools and explicit, server-local group interactions."""

from datetime import datetime, timedelta, timezone
import io
import asyncio
import json
import re

import discord

from adventure_service import parse_time
from adventure_store import MODULES
from bot_domain import safe
from bot_ui import edit_response
from bot_views import BoundModal, reply
from global_views import ScopedView

MENUS = {
    'knowledge': [('units', 'Search units'), ('items', 'Search items'), ('guides', 'Search guides'), ('filter', 'Filter units'), ('compare', 'Compare exact forms'), ('glossary', 'Mechanics glossary')],
    'planning': [('team', 'Save a team'), ('coverage', 'Check team coverage'), ('goal', 'Plan an evolution'), ('materials', 'Record owned materials'), ('owned', 'Owned / wanted units'), ('dps', 'Calculate DPS'), ('chance', 'Calculate chance'), ('budget', 'Calculate attempt budget'), ('farm', 'Estimate farm time'), ('run', 'Record a run'), ('daily', 'Daily modifier guidance'), ('dungeon', 'Dungeon objective guidance'), ('saved', 'My saved entries')],
    'parties': [('party', 'Create a group'), ('groups', 'My groups'), ('template', 'Save group template'), ('templates', 'Use group template')],
    'reminders': [('reminder', 'Create personal reminder'), ('reminders', 'Manage my reminders'), ('preferences', 'Timezone and notifications')],
    'personal': [('saved', 'My saved entries'), ('recent', 'Recent lookups this session'), ('export', 'Export my tool data'), ('erase', 'Delete my optional tool data')],
}


class GameScoped(ScopedView):
    module = None

    def __init__(self, bot, i, **kwargs):
        super().__init__(bot, i, **kwargs)
        home = discord.ui.Button(label='Home', row=4)
        async def go_home(interaction):
            self.require(interaction)
            view=ToolsHome(self.bot,interaction)
            await edit_response(interaction,content=view.description(),view=view)
        home.callback=go_home
        self.add_item(home)

    def require(self, i):
        super().require(i)
        if self.module:
            self.bot.adventures.state.require(i.guild_id,self.module)


class ToolsHome(ScopedView):
    def __init__(self, bot, i, section=None):
        super().__init__(bot, i)
        self.section = section
        self.service = bot.adventures
        options = MENUS.get(section) if section else [('knowledge', 'Units, items and mechanics'), ('planning', 'Teams, evolution and calculators'), ('parties', 'Groups to play together'), ('reminders', 'Personal reminders'), ('personal', 'My optional tool data')]
        choose = discord.ui.Select(placeholder='Choose a tool', options=[discord.SelectOption(label=label, value=value) for value, label in options])
        choose.callback = self.choose
        self.add_item(choose)
        if not (i.permissions.manage_guild or getattr(i.permissions, 'administrator', False)):
            self.remove_item(self.setup)
        if not bot.is_owner_id(i.user.id):
            self.remove_item(self.operations)

    def description(self):
        if self.section:
            return '## Adventures · ' + self.section.title() + '\nChoose a tool. Results and saved entries are private until you explicitly choose to share.'
        return ('## Adventures · game tools\nSearch units, inspect evolution requirements, calculate, save plans and organize local groups.\n\n'
                '**Knowledge:** archived sources with visible dates; current game values may differ.\n**Planning:** manual entries, without accessing your Roblox account.\n'
                '**Groups:** published only after your review in a channel selected by an administrator.\n**Reminders:** private notifications only when you request them.\n\n'
                'Use `/setbanner`, `/dailychallenge` and `/globalchat` for the existing feeds and network conversation.')

    async def choose(self, i):
        self.require(i)
        action = i.data['values'][0]
        if not self.section:
            if action in MODULES:
                self.service.state.require(i.guild_id, action)
            view = ToolsHome(self.bot, i, action)
            await edit_response(i, content=view.description(), view=view); return
        if self.section in MODULES:
            self.service.state.require(i.guild_id, self.section)
        await open_action(self.bot, i, action)

    @discord.ui.button(label='Home', row=1)
    async def home(self, i, button):
        self.require(i)
        view = ToolsHome(self.bot, i)
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.button(label='Server setup', row=1)
    async def setup(self, i, button):
        self.require(i)
        from adventure_admin import SetupView
        view = SetupView(self.bot, i)
        await reply(i, view.description(), view=view)

    @discord.ui.button(label='Private operations', row=1)
    async def operations(self, i, button):
        self.require(i); self.bot.require_owner(i)
        from adventure_admin import ToolOperations
        view = ToolOperations(self.bot, i)
        await reply(i, self.service.operations(), view=view)


FORMS = {
    'units': [('query', 'Unit name or alias', 'Shinobi', True)],
    'items': [('query', 'Item name', 'Star Fruit', True)],
    'guides': [('query', 'Guide or mechanic name', 'Evolution', True)],
    'filter': [('query', 'Unit name fragment, optional', 'Leave empty to filter all exact forms', False), ('damage', 'Damage type, optional', 'magic or physical', False), ('element', 'Element, optional', 'water, lightning...', False), ('placement', 'Placement type, optional', 'Ground, Hill or Hybrid', False)],
    'compare': [('first', 'First exact form or ID', 'Choose exact forms with Search units first', True), ('second', 'Second exact form or ID', '', True)],
    'team': [('name', 'Private team name', 'Dungeon magic', True), ('units', 'Exact unit names or IDs, one per line', '', True), ('notes', 'Your notes, optional', 'Affordable upgrades, manual counters, economy...', False)],
    'coverage': [('units', 'Exact unit names or IDs, one per line', '', True)],
    'goal': [('name', 'Private goal name', 'Next evolution', True), ('unit', 'Exact unit form or ID', '', True), ('priority', 'Priority, optional: 1 highest to 10 lowest', '10', False)],
    'materials': [('materials', 'Owned material totals, one per line', 'Star Fruit=12 (exact names or recipe IDs)', True)],
    'owned': [('unit', 'Exact unit form or ID', '', True), ('status', 'Owned or wanted', 'owned / wanted', True)],
    'dps': [('damage', 'Damage per attack', '', True), ('spa', 'Seconds per attack', '', True), ('crit', 'Critical chance %, optional', '0', False), ('multiplier', 'Critical damage multiplier, optional', '1.5 means 150% damage', False), ('towers', 'Identical placed towers, optional', '1', False)],
    'chance': [('rate', 'Chance per attempt, in percent', '1 means 1%; use a known or hypothetical rate', True), ('attempts', 'Independent attempts', '100', True), ('target', 'Target probability %, optional', '95', False)],
    'budget': [('resources', 'Available resources', '', True), ('price', 'Constant price per attempt', '', True)],
    'farm': [('missing', 'Amount still needed', '', True), ('reward', 'Guaranteed reward per completed run', '', True), ('minutes', 'Average minutes per attempt', '', True), ('success', 'Estimated completion rate %, optional', '100', False)],
    'run': [('name', 'Private run reference', 'Dungeon Friday 1', True), ('mode', 'Mode', '', True), ('minutes', 'Duration in minutes', '', True), ('result', 'Completed or failed', '', True), ('loot', 'Result notes, optional', 'Manual observations; not verified drop rates', False)],
    'daily': [('objective', 'Goal: safety, chests or time', 'safety', True), ('modifiers', 'Modifiers currently shown by the game', 'One per line or separated by commas', True), ('coverage', 'Your team conditions, optional', 'Air access, shields, current resources...', False)],
    'dungeon': [('objective', 'Goal: safety, chests or time', 'chests', True), ('modifiers', 'Available rooms, curses or shop choices', '', True), ('coverage', 'Your team conditions, optional', 'Budget, air access, upgrades already unlocked...', False)],
    'party': [('mode', 'Mode / activity', 'Dungeon farm', True), ('when', 'Start: minutes ahead or local date/time', '30 or 2026-11-01 20:00', True), ('capacity', 'Total places including organizer', '4', True), ('requirements', 'Requirements, optional', 'Manual team expectations; no role changes', False)],
    'template': [('name', 'Private template name', '', True), ('mode', 'Mode / activity', '', True), ('capacity', 'Total places', '4', True), ('requirements', 'Requirements, optional', '', False)],
    'reminder': [('body', 'Private reminder message', '', True), ('when', 'When: minutes ahead or local date/time', '60 or 2026-11-01 20:00-03:00', True)],
    'preferences': [('timezone', 'IANA timezone', 'America/Sao_Paulo', True), ('start', 'Quiet hours start, optional', '0 to 23; leave both boundaries empty to disable', False), ('end', 'Quiet hours end, optional', '0 to 23', False), ('alerts', 'New source update alerts by DM', 'yes or no; only future confirmed updates', True)],
}


class ToolForm(BoundModal):
    def __init__(self, bot, i, action, defaults=None):
        super().__init__(title=dict((v,l) for values in MENUS.values() for v,l in values).get(action, 'Adventures tool')[:45])
        self.bind(bot, i)
        self.action, self.inputs = action, {}
        for key, label, placeholder, required in FORMS[action]:
            if key in ('damage','spa','crit','multiplier','towers','rate','attempts','target','resources','price','missing','reward','minutes','success'):
                placeholder=(placeholder+'; ' if placeholder else '')+'No thousands separators; dot or comma for decimals'
            field = discord.ui.TextInput(required=required, max_length=1200 if key in ('units', 'materials') else 300,
                                         style=discord.TextStyle.paragraph if key in ('units','materials','modifiers','notes','loot','requirements') else discord.TextStyle.short,
                                         placeholder=placeholder[:100] or None, default=(defaults or {}).get(key))
            self.inputs[key] = field
            self.add_item(discord.ui.Label(text=label, component=field))

    async def on_submit(self, i):
        if not await self.interaction_check(i):
            return
        self.bot.require_human(i)
        if not self.bot.globalchat.store.limit('tool-form:'+str(i.user.id),30,60):
            raise ValueError('Please wait before submitting another tool form.')
        values = {key: str(value).strip() for key, value in self.inputs.items()}
        await handle_form(self.bot, i, self.action, values)


async def open_action(bot, i, action):
    if action in FORMS:
        defaults = None
        if action == 'preferences':
            p = bot.adventures.state.preferences(i.user.id)
            defaults = {'timezone': p['timezone'], 'start': str(p['quiet_start']) if p['quiet_start'] is not None else '', 'end': str(p['quiet_end']) if p['quiet_end'] is not None else '', 'alerts': 'yes' if p['feed_alerts'] else 'no'}
        await i.response.send_modal(ToolForm(bot, i, action, defaults)); return
    if action == 'glossary':
        from game_knowledge import GLOSSARY
        view = GlossaryView(bot, i)
        await reply(i, '## Mechanics glossary\nChoose a short explanation.', view=view); return
    if action in ('saved','templates'):
        view = SavedView(bot, i, kind='template' if action == 'templates' else 'favorite')
        await reply(i, view.description(), view=view); return
    if action == 'reminders':
        view = ReminderView(bot, i)
        await reply(i, view.description(), view=view); return
    if action == 'recent':
        view=RecentLookups(bot,i)
        await reply(i,view.description(),view=view);return
    if action == 'groups':
        view = MyGroups(bot, i)
        await reply(i, view.description(), view=view); return
    if action == 'export':
        await i.response.defer(ephemeral=True,thinking=True)
        estimate=bot.adventures.state.one('SELECT COALESCE(sum(length(body)+300),0) n FROM bot_tool_reminders WHERE user=?',(str(i.user.id),))['n']
        estimate+=sum(len(r['data'])+200 for kind in ('favorite','team','goal','owned','run','template') for r in bot.adventures.state.entries(i.user.id,kind))
        async with bot.instance_storage.reserve(0,memory=max(4*1024*1024,6*estimate)):
            data = bot.adventures.state.export_user(i.user.id)
            for entry in data['entries']:entry['data']=json.loads(entry['data'])
            data['recent_lookups_this_server']=bot.adventures.recent_for(i.user.id,i.guild_id)
            raw=json.dumps(data, ensure_ascii=False, indent=2).encode()
            if len(raw)>min(8*1024*1024,i.guild.filesize_limit):
                raise ValueError('The private export exceeds this server\'s upload limit. Contact official support for a bounded export; no saved entries were changed.')
            file = discord.File(io.BytesIO(raw), filename='my-adventures-tools.json')
            try:
                await reply(i, 'Only your optional tool entries are included. Relay receipts and other people\'s data are not exported.', file=file)
            finally:
                file.close()
        return
    if action == 'erase':
        view = EraseTools(bot, i)
        await reply(i, 'Delete your optional favorites, teams, goals and preferences; cancel your reminders and close your groups? This preserves global chat participation, synchronization receipts and votes.', view=view); return
    raise ValueError('Reopen /adventures to choose a current tool.')


async def handle_form(bot, i, action, v):
    service, state = bot.adventures, bot.adventures.state
    module = next((key for key, actions in MENUS.items() if any(a == action for a,_ in actions)), 'planning')
    if module in MODULES:
        state.require(i.guild_id, module)
    if action in ('units','items','guides','filter'):
        kind = 'unit' if action in ('units','filter') else 'item' if action == 'items' else 'guide'
        filters = {'damage_type': v.get('damage'), 'element': v.get('element'), 'tower_type': v.get('placement')} if action == 'filter' else None
        rows = service.knowledge().search(v['query'], kind, filters)
        view = SearchResults(bot, i, rows, kind)
        await reply(i, view.description(), view=view); return
    if action == 'compare':
        await reply(i, service.knowledge().compare(v['first'], v['second']), view=ToolsHome(bot, i, 'knowledge')); return
    if action in ('dps','chance','budget','farm'):
        from game_calculators import dps, chance, budget, farm
        if action == 'dps': result = dps(v['damage'], v['spa'], v['crit'] or 0, v['multiplier'] or 1.5, v['towers'] or 1)
        elif action == 'chance': result = chance(v['rate'], v['attempts'], v['target'] or 95)
        elif action == 'budget': result = budget(v['resources'], v['price'])
        else: result = farm(v['missing'], v['reward'], v['minutes'], v['success'] or 100)
        text = '## ' + action.upper() + ' calculation\nInputs are supplied by you.\n\n'
        for key, value in result.items():
            display=(f'{value:.6g}' if value and abs(value)<.0001 else f'{value:,.4f}'.rstrip('0').rstrip('.')) if isinstance(value,(int,float)) else 'No finite guarantee / unavailable' if value is None else value
            text += key.replace('_',' ').capitalize() + ': ' + display + '\n'
        await reply(i, text, view=ShareResult(bot, i, text)); return
    if action in ('team','coverage'):
        units = [service.knowledge().exact(x.strip())['id'] for x in re.split(r'[;\n]', v['units']) if x.strip()]
        if not 1 <= len(units) <= 6:
            raise ValueError('Choose one to six exact unit forms, one per line.')
        if action == 'team':
            state.save(i.user.id, 'team', v['name'], {'units': units, 'notes': v['notes']})
        await reply(i, service.knowledge().coverage(units), view=ToolsHome(bot, i, 'planning')); return
    if action == 'goal':
        k = service.knowledge(); unit = k.exact(v['unit']); recipe = k.recipe(unit['id'])
        if not recipe:
            raise ValueError('No archived recipe is documented for this exact form. It cannot be turned into an automatic material goal.')
        try: priority = int(v.get('priority') or 10)
        except ValueError: raise ValueError('Goal priority must be a whole number from 1 to 10.') from None
        if not 1 <= priority <= 10: raise ValueError('Goal priority must be from 1 to 10.')
        state.save(i.user.id, 'goal', v['name'], {'unit': unit['id'], 'ingredients': recipe['recipe'], 'source': recipe['stats_source'], 'priority': priority})
        await reply(i, material_goals(service, i.user.id), view=GoalPlan(bot, i)); return
    if action == 'materials':
        from game_calculators import number
        k = service.knowledge(); amounts = {}
        for line in v['materials'].splitlines():
            if '=' not in line:
                raise ValueError('Use one exact material name or recipe ID=amount per line.')
            item, amount = [x.strip() for x in line.split('=', 1)]
            if item not in k.items and not any(item in unit['recipe'] for unit in k.units.values()):
                item=k.exact_item(item)
            amounts[item] = number(amount, 'Owned amount', maximum=1e9)
        state.save(i.user.id, 'owned', 'materials', amounts)
        await reply(i, material_goals(service, i.user.id), view=GoalPlan(bot, i)); return
    if action == 'owned':
        unit = service.knowledge().exact(v['unit'])
        if v['status'].casefold() not in ('owned','wanted'):
            raise ValueError('Choose owned or wanted.')
        state.save(i.user.id, 'owned', unit['id'], {'status': v['status'].casefold()})
        await reply(i, 'Your manual unit list was updated privately.'); return
    if action == 'run':
        from game_calculators import number
        if v['result'].casefold() not in ('completed','failed'):
            raise ValueError('Use completed or failed.')
        state.save(i.user.id, 'run', v['name'], {'mode': v['mode'], 'minutes': number(v['minutes'], 'Minutes', minimum=.01, maximum=1440), 'result': v['result'].casefold(), 'notes': v['loot']})
        await reply(i, 'Run recorded privately. These observations are personal estimates, not verified game drop rates.'); return
    if action in ('daily','dungeon'):
        from game_knowledge import advisor
        objective = v['objective'].casefold()
        if objective not in ('safety','chests','time'):
            raise ValueError('Choose safety, chests or time.')
        text = advisor(action, objective, v['modifiers'], v['coverage'])
        await reply(i, text, view=ShareResult(bot, i, text)); return
    if action == 'party':
        if not bot.globalchat.store.limit('tool-party-create:'+str(i.user.id),10,3600):
            raise ValueError('Please wait before creating another group. Your existing groups remain available.')
        settings = state.settings(i.guild_id)[0]
        if not settings.get('party_channel'):
            raise ValueError('An administrator must choose a group channel in Server setup first.')
        try: capacity = int(v['capacity'])
        except ValueError: raise ValueError('Places must be a whole number from 2 to 12.') from None
        when = parse_time(v['when'], state.preferences(i.user.id)['timezone'], state.clock())
        ident = state.party(i.guild_id, settings['party_channel'], i.user.id, v['mode'], when, capacity, v['requirements'])
        row = state.party_record(ident, i.guild_id)
        view = PartyPreview(bot, i, ident)
        await reply(i, service.party_text(row) + '\n\nPrivate draft. Review before publishing.', view=view); return
    if action == 'template':
        try: capacity = int(v['capacity'])
        except ValueError: raise ValueError('Places must be a whole number from 2 to 12.') from None
        if not 2 <= capacity <= 12: raise ValueError('Choose 2 to 12 places.')
        state.save(i.user.id, 'template', v['name'], {'mode': v['mode'], 'capacity': capacity, 'requirements': v['requirements']})
        await reply(i, 'Private group template saved. Use My saved entries → Template to create its next group.'); return
    if action == 'reminder':
        if not bot.globalchat.store.limit('tool-reminder-create:'+str(i.user.id),15,3600):
            raise ValueError('Please wait before creating another reminder. Existing reminders can still be cancelled.')
        when = parse_time(v['when'], state.preferences(i.user.id)['timezone'], state.clock())
        ident = state.reminder(i.user.id, i.guild_id, v['body'], when)
        await reply(i, f'Reminder `{ident}` scheduled for <t:{int(when)}:F>. You requested a private DM. You can cancel it in Manage my reminders.', view=ReminderView(bot, i)); return
    if action == 'preferences':
        if v['alerts'].casefold() not in ('yes','no'):
            raise ValueError('Choose yes or no for optional source-update notifications.')
        try: start, end = (int(v['start']) if v['start'] else None), (int(v['end']) if v['end'] else None)
        except ValueError: raise ValueError('Quiet hours use whole hours from 0 to 23.') from None
        state.set_preferences(i.user.id, v['timezone'], start, end, v['alerts'].casefold() == 'yes', i.guild_id)
        await reply(i, 'Your timezone and notification preferences were saved. Source alerts refer to future confirmed updates; no reset time or character identification is inferred.'); return
    raise ValueError('This form is no longer available. Reopen /adventures.')


def material_goals(service, user, page=0):
    from game_calculators import allocate
    goals = service.state.entries(user, 'goal')
    stock = next((json.loads(x['data']) for x in service.state.entries(user, 'owned') if x['name'] == 'materials'), {})
    goals.sort(key=lambda g:(json.loads(g['data']).get('priority',10),g['updated'],g['name']))
    ordered = [(g['name'], json.loads(g['data'])['ingredients']) for g in goals]
    page=max(0,min(page,max(0,(len(goals)-1)//2)))
    text = f'## Shared material plan · page {page+1}/{max(1,(len(goals)+1)//2)}\nManual totals; each ingredient is allocated once across all pages. Lower priority numbers come first, then oldest saved goal. Save the same goal name to change its priority.\n'
    for row in allocate(ordered, stock)[page*2:page*2+2]:
        source = json.loads(next(g['data'] for g in goals if g['name']==row['goal'])).get('source',{})
        text += '\n**' + safe(row['goal'], 80) + '** · historical recipe ' + safe(source.get('date','unknown')[:10]) + '\n' + ('\n'.join(f"{amount:g} × {safe(service.knowledge().item_name(item), 80)}" for item,amount in row['missing'].items()) or 'Recorded materials cover this archived recipe.') + '\n'
    return text if goals else text + '\nCreate an evolution goal first.'


class GoalPlan(GameScoped):
    def __init__(self,bot,i,page=0):
        super().__init__(bot,i)
        count=len(bot.adventures.state.entries(i.user.id,'goal'))
        self.page=max(0,min(page,max(0,(count-1)//2)))
        self.previous.disabled=self.page==0
        self.next.disabled=(self.page+1)*2>=count

    @discord.ui.button(label='Previous',row=0)
    async def previous(self,i,button):
        self.require(i)
        view=GoalPlan(self.bot,i,self.page-1)
        await edit_response(i,content=material_goals(self.bot.adventures,i.user.id,view.page),view=view)

    @discord.ui.button(label='Next',row=0)
    async def next(self,i,button):
        self.require(i)
        view=GoalPlan(self.bot,i,self.page+1)
        await edit_response(i,content=material_goals(self.bot.adventures,i.user.id,view.page),view=view)


class SearchResults(ScopedView):
    def __init__(self, bot, i, rows, kind, page=0):
        super().__init__(bot, i)
        self.rows, self.kind, self.page = rows, kind, page
        selected = rows[page*20:page*20+20]
        self.choose.options = [discord.SelectOption(label=r['name'][:100], value=r['id'][:100], description=('Exact form · historical source' if kind == 'unit' else 'Historical source')) for r in selected] or [discord.SelectOption(label='No matches', value='none')]
        self.choose.disabled = not selected
        self.previous.disabled = page == 0
        self.next.disabled = (page+1)*20 >= len(rows)

    def description(self):
        return f'## Search results · {self.page+1}\n{len(self.rows)} matches. Choose the exact entry; all imported game facts show their source date.'

    @discord.ui.select(placeholder='Choose an exact entry')
    async def choose(self, i, select):
        self.require(i); self.bot.adventures.state.require(i.guild_id, 'knowledge')
        ident = select.values[0]
        if ident not in {r['id'] for r in self.rows[self.page*20:self.page*20+20]}:
            raise ValueError('Choose an entry from this results page.')
        view = DetailView(self.bot, i, ident, self.kind, self)
        self.bot.adventures.remember(i.user.id,i.guild_id,self.kind,ident)
        await edit_response(i, content=self.bot.adventures.knowledge().card(ident, self.kind), view=view)

    @discord.ui.button(label='Previous', row=1)
    async def previous(self, i, button):
        self.require(i)
        view = SearchResults(self.bot, i, self.rows, self.kind, self.page-1)
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.button(label='Next', row=1)
    async def next(self, i, button):
        self.require(i)
        view = SearchResults(self.bot, i, self.rows, self.kind, self.page+1)
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.button(label='Home', row=1)
    async def home(self, i, button):
        self.require(i)
        view = ToolsHome(self.bot, i)
        await edit_response(i, content=view.description(), view=view)


class DetailView(GameScoped):
    module='knowledge'
    def __init__(self, bot, i, ident, kind, results):
        super().__init__(bot, i)
        self.ident, self.kind, self.results, self.upgrade_page = ident, kind, results, 0
        if kind != 'unit':
            self.remove_item(self.evolution); self.remove_item(self.upgrades)

    @discord.ui.button(label='Evolution', row=0)
    async def evolution(self, i, button):
        self.require(i)
        await reply(i, self.bot.adventures.knowledge().evolution(self.ident))

    @discord.ui.button(label='Upgrades', row=0)
    async def upgrades(self, i, button):
        self.require(i)
        k = self.bot.adventures.knowledge()
        pages = max(1, (len(k.units[self.ident]['upgrades'])+4)//5)
        await reply(i, k.upgrades(self.ident, self.upgrade_page))
        self.upgrade_page = (self.upgrade_page+1) % pages

    @discord.ui.button(label='Favorite', row=0)
    async def favorite(self, i, button):
        self.require(i)
        self.bot.adventures.state.save(i.user.id, 'favorite', self.kind + ':' + self.ident, {'kind': self.kind, 'id': self.ident})
        await reply(i, 'Saved privately in My saved entries → Favorite.')

    @discord.ui.button(label='Share preview', row=1)
    async def share(self, i, button):
        self.require(i)
        text = self.bot.adventures.knowledge().card(self.ident, self.kind)
        await reply(i, text, view=ShareResult(self.bot, i, text, module='knowledge'))

    @discord.ui.button(label='Back to results', row=1)
    async def back(self, i, button):
        self.require(i)
        await edit_response(i, content=self.results.description(), view=self.results)


class RecentLookups(GameScoped):
    module='knowledge'
    def __init__(self,bot,i):
        super().__init__(bot,i)
        self.rows=bot.adventures.recent_for(i.user.id,i.guild_id)
        k=bot.adventures.knowledge()
        self.choose.options=[discord.SelectOption(label=(k.units if r['kind']=='unit' else k.items if r['kind']=='item' else k.guides).get(r['id'],{}).get('name',r['id'])[:100],value=str(n)) for n,r in enumerate(self.rows)] or [discord.SelectOption(label='No recent lookups',value='none')]
        self.choose.disabled=not self.rows

    def description(self):
        return '## Recent lookups\nYour last ten lookups in this server for this session. Entries expire after 30 minutes and are cleared on restart; use Favorite to save one explicitly.'

    @discord.ui.select(placeholder='Open a recent lookup')
    async def choose(self,i,select):
        self.require(i)
        try:row=self.rows[int(select.values[0])]
        except (ValueError,IndexError):raise ValueError('Choose a recent entry.') from None
        view=DetailView(self.bot,i,row['id'],row['kind'],self)
        await edit_response(i,content=self.bot.adventures.knowledge().card(row['id'],row['kind']),view=view)


class ShareResult(GameScoped):
    def __init__(self, bot, i, text, module='planning'):
        super().__init__(bot, i)
        self.text = text
        self.shared = False
        self.module=module

    @discord.ui.button(label='Share in this channel', row=0)
    async def share(self, i, button):
        self.require(i)
        if self.shared:
            raise ValueError('This preview was already shared. Open a new preview if you need another copy.')
        self.bot.adventures.normal_channel(i.channel, i.user)
        if not self.bot.globalchat.store.limit('tool-share:'+str(i.user.id), 2, 60):
            raise ValueError('Please wait before sharing another result.')
        self.shared = True  # Ambiguous acceptance must not cause a second publication.
        await i.response.defer(ephemeral=True, thinking=True)
        from bot_ui import payload
        await i.channel.send(**payload(bot=self.bot, content=self.text, allowed_mentions=discord.AllowedMentions.none()))
        await reply(i, 'Shared once in this channel after your confirmation.')


class GlossaryView(GameScoped):
    module='knowledge'
    def __init__(self, bot, i):
        super().__init__(bot, i)
        from game_knowledge import GLOSSARY
        self.choose.options = [discord.SelectOption(label=k, value=k) for k in GLOSSARY]

    @discord.ui.select(placeholder='Choose a mechanic')
    async def choose(self, i, select):
        self.require(i)
        from game_knowledge import GLOSSARY
        await reply(i, '## ' + select.values[0] + '\n' + GLOSSARY[select.values[0]])


class SavedView(GameScoped):
    def __init__(self, bot, i, kind='favorite', page=0):
        super().__init__(bot, i)
        self.kind, self.page = kind, page
        self.rows = bot.adventures.state.entries(i.user.id, kind)
        self.choose.options = [discord.SelectOption(label=r['name'][:100], value=str(n)) for n,r in enumerate(self.rows[page*20:page*20+20], page*20)] or [discord.SelectOption(label='No saved entries', value='none')]
        self.choose.disabled = not self.rows
        self.previous.disabled = page == 0
        self.next.disabled = (page+1)*20 >= len(self.rows)
        self.kind_select.options = [discord.SelectOption(label=x.title(), value=x, default=x==kind) for x in ('favorite','team','goal','owned','run','template')]
        self.selected = None
        self.remove.disabled = True
        self.share_team.disabled = True

    def description(self):
        return f'## My {self.kind} entries · page {self.page+1}\n{len(self.rows)} private saved entries. Choose one to read or remove. Unit/material ownership is entered manually.'

    @discord.ui.select(placeholder='Entry category', row=0)
    async def kind_select(self, i, select):
        self.require(i)
        view = SavedView(self.bot, i, select.values[0])
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.select(placeholder='Choose a saved entry', row=1)
    async def choose(self, i, select):
        self.require(i)
        try: row = self.rows[int(select.values[0])]
        except (ValueError, IndexError): raise ValueError('Choose an entry from this page.') from None
        current = next((r for r in self.bot.adventures.state.entries(i.user.id, self.kind) if r['name']==row['name']), None)
        if current is None: raise ValueError('This entry changed. Reopen My saved entries.')
        self.selected = current['name']; self.remove.disabled = False
        self.share_team.disabled = self.kind!='team'
        data = json.loads(current['data'])
        if self.kind == 'favorite':
            text = self.bot.adventures.knowledge().card(data['id'], data['kind'])
        elif self.kind == 'team':
            text = self.bot.adventures.knowledge().coverage(data['units']) + '\n\nYour notes: ' + safe(data.get('notes',''), 300)
        elif self.kind == 'goal':
            view=GoalPlan(self.bot,i)
            await reply(i,material_goals(self.bot.adventures,i.user.id),view=view);return
        elif self.kind == 'template':
            await i.response.send_modal(ToolForm(self.bot, i, 'party', {'mode': data['mode'], 'capacity': str(data['capacity']), 'requirements': data['requirements'], 'when': '30'})); return
        else:
            text = '**' + safe(current['name'], 80) + '**\n' + '\n'.join(f'{safe(k,80)}: {safe(v,200)}' for k,v in data.items())
        await edit_response(i, content=text[:3400], view=self)

    @discord.ui.button(label='Remove selected', row=2)
    async def remove(self, i, button):
        self.require(i)
        if self.selected:
            self.bot.adventures.state.remove(i.user.id, self.kind, self.selected)
        view = SavedView(self.bot, i, self.kind)
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.button(label='Preview selected team for sharing',row=3)
    async def share_team(self,i,button):
        self.require(i)
        if self.kind!='team' or self.selected is None:raise ValueError('Choose one of your saved teams first.')
        row=next((r for r in self.bot.adventures.state.entries(i.user.id,'team') if r['name']==self.selected),None)
        if not row:raise ValueError('This team changed. Reopen My saved entries.')
        data=json.loads(row['data'])
        text=self.bot.adventures.knowledge().coverage(data['units'])+'\n\nShared team: '+safe(row['name'],80)+'\nYour notes: '+safe(data.get('notes',''),300)
        await reply(i,text,view=ShareResult(self.bot,i,text))

    @discord.ui.button(label='Previous', row=2)
    async def previous(self, i, button):
        self.require(i)
        view = SavedView(self.bot, i, self.kind, max(0,self.page-1))
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.button(label='Next', row=2)
    async def next(self, i, button):
        self.require(i)
        view = SavedView(self.bot, i, self.kind, self.page+1)
        await edit_response(i, content=view.description(), view=view)


class ReminderView(GameScoped):
    def __init__(self, bot, i):
        super().__init__(bot, i)
        self.rows = bot.adventures.state.rows('SELECT id,body,due,state,error FROM bot_tool_reminders WHERE user=? ORDER BY created DESC LIMIT 20', (str(i.user.id),))
        self.choose.options = [discord.SelectOption(label=(r['body'] or 'Cancelled reminder')[:80], value=r['id'], description=r['state']) for r in self.rows] or [discord.SelectOption(label='No reminders', value='none')]
        self.choose.disabled = not self.rows
        self.selected = None
        self.cancel.disabled = self.snooze.disabled = True

    def description(self):
        return '## My reminders\n' + ('\n\n'.join(f"`{r['id']}` · {r['state']} · <t:{int(r['due'])}:F>\n{safe(r['body'],150)}\n{safe(r['error'],180)}" for r in self.rows[:6]) or 'No reminders. Create one to opt into a private notification.')

    @discord.ui.select(placeholder='Choose your reminder')
    async def choose(self, i, select):
        self.require(i)
        row = next((r for r in self.rows if r['id']==select.values[0]), None)
        if not row: raise ValueError('Choose one of your reminders.')
        self.selected = row['id']; self.cancel.disabled = False; self.snooze.disabled = False
        await edit_response(i, content=f"**{safe(row['body'],300)}**\n{row['state']} · <t:{int(row['due'])}:F>\n{safe(row['error'],300)}", view=self)

    @discord.ui.button(label='Cancel selected', row=1)
    async def cancel(self, i, button):
        self.require(i)
        self.bot.adventures.state.cancel(i.user.id, self.selected)
        view = ReminderView(self.bot, i)
        await edit_response(i, content=view.description(), view=view)

    @discord.ui.button(label='Remind again in 10 minutes', row=1)
    async def snooze(self, i, button):
        self.require(i)
        if not self.bot.globalchat.store.limit('tool-reminder-create:'+str(i.user.id),15,3600):
            raise ValueError('Please wait before creating another reminder.')
        self.bot.adventures.state.snooze(i.user.id, self.selected)
        view = ReminderView(self.bot, i)
        await edit_response(i, content=view.description(), view=view)


class EraseTools(GameScoped):
    @discord.ui.button(label='Confirm deletion of my optional data', style=discord.ButtonStyle.danger)
    async def erase(self, i, button):
        self.require(i)
        self.bot.adventures.state.erase_user(i.user.id)
        self.bot.adventures.clear_recent(i.user.id)
        self.erase.disabled = True
        await edit_response(i, content='Your optional tool data was removed. Reminders were cancelled and your groups were closed. Feed votes, relay records and participation were preserved.', view=self)


class PartyPreview(GameScoped):
    def __init__(self, bot, i, ident):
        super().__init__(bot, i)
        self.ident = ident
        self.publish.disabled=bot.adventures.state.party_record(ident,i.guild_id)['state']!='draft'

    @discord.ui.button(label='Publish reviewed group', style=discord.ButtonStyle.success)
    async def publish(self, i, button):
        self.require(i)
        await i.response.defer(ephemeral=True, thinking=True)
        row = await self.bot.adventures.publish_party(self.ident, i)
        await reply(i, f"Group published in <#{row['channel']}>. [Open group](https://discord.com/channels/{row['guild']}/{row['channel']}/{row['message']}).")

    @discord.ui.button(label='Close my group',row=1)
    async def close_group(self,i,button):
        self.require(i)
        state=self.bot.adventures.state
        row=state.party_record(self.ident,i.guild_id)
        if row['owner']!=str(i.user.id):raise ValueError('Only the organizer can close this group.')
        with state.db:state.db.execute("UPDATE bot_tool_parties SET state='closed',version=version+1 WHERE id=?",(self.ident,))
        await reply(i,'Your group was closed. Its existing message will show the closure when Discord permits the update.')


class PartyAction(discord.ui.DynamicItem[discord.ui.Button], template=r'adventure:party:(?P<action>join|leave|ready|unready|refresh|close|event):(?P<ident>[a-f0-9]{12})'):
    def __init__(self, action, ident, disabled=False):
        super().__init__(discord.ui.Button(label={'join':'Join / waiting list','leave':'Leave','ready':'Ready','unready':'Not ready','refresh':'Refresh','close':'Close group','event':'Schedule event'}[action], custom_id=f'adventure:party:{action}:{ident}', disabled=disabled))
        self.action, self.ident = action, ident

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['action'], match['ident'])

    async def callback(self, i):
        try:
            bot = i.client; bot.require_human(i)
            service, state = bot.adventures, bot.adventures.state
            row = state.party_record(self.ident, i.guild_id)
            if str(i.channel_id) != row['channel'] or str(i.message.id) != row['message']:
                raise ValueError('Open the current group message in its original server channel.')
            service.normal_channel(i.channel, i.user, party=True)
            if self.action in ('close','event') and row['owner'] != str(i.user.id):
                raise ValueError('Only the organizer can perform this group action.')
            if self.action == 'event':
                state.require(i.guild_id,'events')
                if row['state'] != 'open' or row['event'] or row['starts'] <= state.clock():
                    raise ValueError('An event can be created once for an open future group. Check the server event list if confirmation is pending.')
                if not i.guild.me.guild_permissions.create_events:
                    raise ValueError('An administrator must grant Create Events to enable this optional action.')
                with state.db:
                    claim = state.db.execute("UPDATE bot_tool_parties SET event='pending' WHERE id=? AND event IS NULL AND state='open'", (self.ident,))
                if claim.rowcount != 1: raise ValueError('Event creation is already being confirmed.')
                await i.response.defer(ephemeral=True, thinking=True)
                event = await asyncio.wait_for(i.guild.create_scheduled_event(name=row['mode'][:100], start_time=datetime.fromtimestamp(row['starts'], timezone.utc), end_time=datetime.fromtimestamp(row['expires'], timezone.utc), entity_type=discord.EntityType.external, privacy_level=discord.PrivacyLevel.guild_only, location=f"Group in #{i.channel.name}"[:100], description='Join the group message to reserve a place. Marking Interested does not reserve a place. Group '+self.ident, reason='Organizer requested an Adventures group event'),20)
                with state.db: state.db.execute('UPDATE bot_tool_parties SET event=? WHERE id=?', (str(event.id), self.ident))
                await reply(i, 'The server event was created. Group places are still controlled by the group message.'); return
            if self.action == 'close':
                with state.db: state.db.execute("UPDATE bot_tool_parties SET state='closed',version=version+1 WHERE id=?", (self.ident,))
            elif self.action != 'refresh':
                state.join(self.ident, i.guild_id, i.user.id, ready=self.action=='ready', leave=self.action=='leave',unready=self.action=='unready')
            await i.response.defer(ephemeral=True, thinking=True)
            await service.refresh_party(state.party_record(self.ident, i.guild_id))
            await reply(i, 'Group updated. If all places are occupied, new participants are listed as reserves.')
        except ValueError as error:
            await reply(i, str(error))
        except Exception:
            from bot_views import action_error
            await reply(i, action_error(None))


class PartyView(discord.ui.View):
    def __init__(self, ident, closed=False,events=False):
        super().__init__(timeout=None)
        for action in ('join','leave','ready','unready','refresh','close','event'):
            self.add_item(PartyAction(action, ident, closed and action != 'refresh' or action=='event' and not events))


class MyGroups(GameScoped):
    def __init__(self, bot, i):
        super().__init__(bot, i)
        self.rows = bot.adventures.state.rows('SELECT * FROM bot_tool_parties WHERE guild=? AND owner=? ORDER BY created DESC LIMIT 10', (str(i.guild_id),str(i.user.id)))
        self.choose.options = [discord.SelectOption(label=r['mode'][:100], value=r['id'], description=r['state']) for r in self.rows] or [discord.SelectOption(label='No groups', value='none')]
        self.choose.disabled = not self.rows

    def description(self):
        return '## My groups\nChoose one to review its state or publish a draft. Groups expire two hours after the selected start time.'

    @discord.ui.select(placeholder='Choose your group')
    async def choose(self, i, select):
        self.require(i)
        if select.values[0] not in {r['id'] for r in self.rows}: raise ValueError('Choose one of your groups.')
        row = self.bot.adventures.state.party_record(select.values[0], i.guild_id)
        view = PartyPreview(self.bot, i, row['id'])
        text = self.bot.adventures.party_text(row)
        if row['message']: text += f"\n[Open group](https://discord.com/channels/{row['guild']}/{row['channel']}/{row['message']})"
        await reply(i, text, view=view)
