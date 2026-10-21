import hashlib
import struct
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import discord

import bot as app
import quiz_icons as icons
import quiz_ui as screen
from test_session import Channel, user, view_text


class IconTests(unittest.IsolatedAsyncioTestCase):
    def test_uploads_are_small_rgba_pngs_derived_from_original_wiki_images(self):
        names = set()
        for key, icon in icons.ICONS.items():
            asset = icons.asset(key)
            self.assertTrue(asset['transparent'])
            self.assertTrue(asset['colored'])
            if asset.get('original_path'):
                original = Path(__file__).resolve().parents[1] / asset['original_path']
                self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), asset['original_sha256'])
                self.assertIs(asset['processing']['recolored'], False)
            else:
                self.assertEqual(asset['sha256'], asset['original_sha256'])
            self.assertFalse(icon['processing']['generation'])
            raw = (Path(__file__).resolve().parents[1] / icon['upload_path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), icon['upload_sha256'])
            self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
            width, height, depth, color = struct.unpack('>IIBB', raw[16:26])
            self.assertLessEqual(max(width, height), 128)
            self.assertEqual((depth, color), (8, 6))  # RGBA, not an opaque RGB conversion.
            self.assertLess(len(raw), 256000)
            self.assertNotIn(icon['name'], names)
            names.add(icon['name'])

    async def test_registered_game_icons_are_used_in_buttons_and_category_menus(self):
        mapping = {key: {**value, 'id': str(1500000000000000000 + i)} for i, (key, value) in enumerate(icons.ICONS.items())}
        with patch.dict(icons.ICONS, mapping, clear=True):
            s = app.QuizSession(Channel(), user(), None)
            view = screen.lobby_panel(s, app.handle_control)
            start = next(i for i in view.walk_children() if getattr(i, 'custom_id', '') == 'aa:start')
            self.assertEqual(start.emoji.id, int(mapping['summon']['id']))
            select = next(i for i in view.walk_children() if getattr(i, 'custom_id', '') == 'aa:category')
            self.assertTrue(all(o.emoji.id for o in select.options))
            payload = discord.http.handle_message_parameters(view=view).payload
            self.assertEqual(payload['flags'] & 32768, 32768)
            self.assertIn(str(mapping['clock']['id']), view_text(view))
            self.assertLessEqual(view.total_children_count, 40)

    async def test_plain_text_remains_usable_if_application_icons_are_not_registered(self):
        mapping = {key: {**value, 'id': None} for key, value in icons.ICONS.items()}
        with patch.dict(icons.ICONS, mapping, clear=True):
            s = app.QuizSession(Channel(), user(), None)
            view = screen.lobby_panel(s, app.handle_control)
            self.assertIn('01 · Assuntos', view_text(view))
            self.assertNotIn('<:', view_text(view))
            start = next(i for i in view.walk_children() if getattr(i, 'custom_id', '') == 'aa:start')
            self.assertIsNone(start.emoji)
            self.assertEqual(start.label, 'Começar')

    async def test_rarity_category_icon_cannot_signal_the_correct_rarity(self):
        s = app.QuizSession(Channel(), user(), None)
        s.ends_at = datetime.now(timezone.utc)
        headers = []
        for identifier in ('rarity:tanjiro', 'rarity:broly', 'rarity:inosuke'):
            s.current_question = next(q for q in app.PACK.questions if q.id == identifier)
            panel = screen.question_panel(s, app.handle_control, 45)
            headers.append(panel.children[0].to_component_dict())
        self.assertEqual(headers[0], headers[1])
        self.assertEqual(headers[1], headers[2])

    async def test_reroll_item_question_cannot_show_its_answer_as_a_category_icon(self):
        s = app.QuizSession(Channel(), user(), None)
        s.ends_at = datetime.now(timezone.utc)
        s.current_question = next(q for q in app.PACK.questions if q.id == 'trait:item')
        panel = screen.question_panel(s, app.handle_control, 45)
        payload = str(panel.to_components())
        self.assertNotIn('item-star-remnant', payload)
        if icons.ICONS['traits']['id']:
            self.assertNotIn(icons.ICONS['traits']['id'], payload)
