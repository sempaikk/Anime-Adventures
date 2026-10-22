"""V2 protocol boundaries, private controls and native file compatibility."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import aiohttp
import discord
from discord.components import _component_factory
from discord.http import handle_message_parameters

import test_tier_thread as runtime
from quiz_icons import ICONS
from tier_style import GameTheme, icon_sources
from tier_ui import Card, payload, visible_text, component_dicts, message_files
from tier_views import (
    AdminView,
    ThreadView,
    PollView,
    ImageModal,
    CorrectionModal,
    ReportModal,
)
from tier_image import poll_embed


class NativeProtocolCase(unittest.IsolatedAsyncioTestCase):
    async def test_only_matching_application_icon_ids_and_names_are_enabled(self):
        theme = GameTheme()
        first, second = list(ICONS)[:2]
        api = SimpleNamespace(
            get_application_emojis=AsyncMock(
                return_value={
                    "items": [
                        {"id": ICONS[first]["id"], "name": ICONS[first]["name"]},
                        {"id": ICONS[second]["id"], "name": "unrelated"},
                    ]
                }
            )
        )
        await theme.refresh(api, 42)
        self.assertEqual(theme.available, {first})
        api.get_application_emojis.assert_awaited_once_with(42)

    async def test_icon_connection_failure_preserves_readable_controls(self):
        theme = GameTheme()
        theme.available = set(ICONS)
        await theme.refresh(
            SimpleNamespace(
                get_application_emojis=AsyncMock(
                    side_effect=aiohttp.ClientConnectionError
                )
            ),
            42,
        )
        view = ThreadView(SimpleNamespace(ui_theme=theme))
        self.assertTrue(all(item.emoji is None for item in view.children))
        self.assertEqual(
            [item.label for item in view.children],
            ["Sugerir imagem", "Meus envios", "Como funciona"],
        )

    async def test_missing_application_id_does_not_try_a_network_request(self):
        api = SimpleNamespace(get_application_emojis=AsyncMock())
        await GameTheme().refresh(api, None)
        api.get_application_emojis.assert_not_awaited()

    def test_icon_sources_belong_to_the_game_wiki(self):
        self.assertTrue(
            all(
                url.startswith("https://animeadventures.fandom.com/wiki/File:")
                for url in icon_sources().values()
            )
        )

    def test_new_interface_has_native_v2_flag_and_no_legacy_content_or_embed(self):
        data = payload(content="## Título\n\n**Detalhes**")
        with handle_message_parameters(**data) as request:
            self.assertEqual(request.payload["flags"] & 32768, 32768)
            self.assertIsNone(request.payload["content"])
            self.assertEqual(request.payload["embeds"], [])
        self.assertIn("Detalhes", visible_text(data["view"]))

    def test_private_flag_survives_native_v2_serialization(self):
        flags = discord.MessageFlags(ephemeral=True)
        with handle_message_parameters(
            **payload(content="Voto registrado"), flags=flags
        ) as request:
            self.assertTrue(request.payload["flags"] & 32768)
            self.assertTrue(request.payload["flags"] & 64)

    def test_standalone_classification_png_does_not_become_a_v2_card(self):
        original = {"attachments": [], "content": None, "view": None, "embeds": []}
        self.assertEqual(payload(**original), original)

    async def test_native_file_download_works_without_message_attachments(self):
        state = SimpleNamespace(
            http=SimpleNamespace(get_from_cdn=AsyncMock(return_value=b"verified bytes"))
        )
        component = _component_factory(
            {
                "type": 13,
                "name": "retratos-pendentes.txt",
                "file": {
                    "url": "https://cdn.discordapp.com/attachments/1/2/retratos-pendentes.txt",
                    "attachment_id": "2",
                },
            },
            state=state,
        )
        message = SimpleNamespace(attachments=[], components=[component])
        files = message_files(message)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].filename, "retratos-pendentes.txt")
        self.assertEqual(await files[0].read(), b"verified bytes")

    def test_external_wiki_thumbnail_is_not_treated_as_an_uploaded_file(self):
        component = _component_factory(
            {
                "type": 9,
                "components": [{"type": 10, "content": "Retrato"}],
                "accessory": {
                    "type": 11,
                    "media": {"url": "https://example.com/portrait.png"},
                },
            }
        )
        self.assertEqual(
            message_files(SimpleNamespace(attachments=[], components=[component])), []
        )

    async def test_file_without_nested_sdk_state_uses_its_parent_message_connection(
        self,
    ):
        state = SimpleNamespace(
            http=SimpleNamespace(
                get_from_cdn=AsyncMock(return_value=b"native file bytes")
            )
        )
        component = _component_factory(
            {
                "type": 13,
                "name": "native.txt",
                "file": {
                    "url": "https://cdn.discordapp.com/attachments/1/2/native.txt",
                    "attachment_id": "2",
                },
            }
        )
        message = SimpleNamespace(attachments=[], components=[component], _state=state)
        self.assertEqual(await message_files(message)[0].read(), b"native file bytes")

    def test_native_media_gallery_and_legacy_attachment_are_deduplicated(self):
        attachment = SimpleNamespace(id=2)
        component = _component_factory(
            {
                "type": 12,
                "items": [
                    {
                        "media": {
                            "url": "https://cdn.discordapp.com/attachments/1/2/image.png",
                            "attachment_id": "2",
                        }
                    }
                ],
            }
        )
        self.assertEqual(
            message_files(
                SimpleNamespace(attachments=[attachment], components=[component])
            ),
            [attachment],
        )

    def test_overlong_card_is_rejected_before_any_request(self):
        with self.assertRaises(ValueError):
            payload(content="x" * 4001)


class NativeRuntimeCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = runtime.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = runtime.ThreadRuntimeCase.asyncTearDown
    interaction = runtime.ThreadRuntimeCase.interaction
    setup_panel = runtime.ThreadRuntimeCase.setup_panel
    propose = runtime.ThreadRuntimeCase.propose

    async def test_private_admin_card_delegates_actor_and_permission_checks(self):
        owner = self.interaction()
        view = payload(
            bot=self.app, content="Painel privado", view=AdminView(self.app, owner)
        )["view"]
        self.assertIsInstance(view, Card)
        self.assertFalse(await view.interaction_check(self.interaction(user=8)))
        self.assertTrue(await view.interaction_check(owner))

    async def test_member_index_callback_still_validates_official_message(self):
        await self.setup_panel()
        controller = ThreadView(self.app)
        view = payload(bot=self.app, content="Participar", view=controller)["view"]
        i = self.interaction(admin=False, user=8, channel=self.env.thread)
        i.message = SimpleNamespace(id=123)
        button = next(
            item
            for item in view.walk_children()
            if getattr(item, "custom_id", None) == "tier:v3:help"
        )
        with self.assertRaisesRegex(ValueError, "tópico oficial"):
            await button.callback(i)
        i.message.id = int(self.app.store.thread(1)["intro_id"])
        await button.callback(i)
        self.assertTrue(i.response.send_message.await_args.kwargs["ephemeral"])
        self.assertIsInstance(
            i.response.send_message.await_args.kwargs["view"], discord.ui.LayoutView
        )

    async def test_stopped_private_controller_cannot_be_reused_through_new_layout(self):
        controller = AdminView(self.app, self.interaction())
        view = payload(content="Painel", view=controller)["view"]
        controller.stop()
        self.assertFalse(await view.interaction_check(self.interaction()))

    async def test_server_admin_never_receives_owner_actions_in_native_tree(self):
        data = payload(
            bot=self.app,
            content="Painel local",
            view=AdminView(self.app, self.interaction(user=8)),
        )
        buttons = [
            item for item in component_dicts(data["view"]) if item.get("type") == 2
        ]
        self.assertEqual([item["label"] for item in buttons], ["Conferir painel"])
        self.assertNotIn("Correções", visible_text(data["view"]))

    async def test_public_controls_are_persistent_and_semantic_icons_are_selective(
        self,
    ):
        self.app.ui_theme.available = set(ICONS)
        thread = ThreadView(self.app)
        view = payload(bot=self.app, content="Índice", view=thread)["view"]
        self.assertTrue(view.is_persistent())
        self.assertIsNone(thread.suggest.emoji)
        poll = PollView(self.app)
        self.assertIsNone(poll.tests.emoji)
        self.assertIsNone(poll.report.emoji)
        self.assertIsNone(poll.approve.emoji)

    async def test_modals_use_labels_and_file_uploads_without_deprecated_action_rows(
        self,
    ):
        modal = ImageModal(self.app, self.interaction())
        parts = modal.to_components()
        self.assertEqual(len(parts), 5)
        self.assertTrue(
            all(part["type"] == 18 and part.get("description") for part in parts)
        )
        self.assertTrue(all(not part["component"].get("label") for part in parts))
        for form in (
            ReportModal(self.app, self.interaction(), 1),
            CorrectionModal(self.app, self.interaction()),
        ):
            self.assertEqual(form.to_components()[0]["type"], 18)

    async def test_confirmation_is_private_native_and_keeps_vote_deadline(self):
        await self.setup_panel()
        proposal = self.propose()
        await self.app.poll_loop.coro(self.app)
        receipt = self.app.store.poll_messages()[0]
        i = self.interaction(admin=False, user=8, channel=self.env.channel)
        i.message = SimpleNamespace(id=int(receipt["message_id"]))
        await PollView(self.app).cast(i, "approve")
        call = i.response.send_message.await_args
        self.assertTrue(call.kwargs["ephemeral"])
        self.assertIsInstance(call.kwargs["view"], discord.ui.LayoutView)
        self.assertIn(
            f"<t:{int(self.app.store.proposal(proposal['id'])['closes_at'])}:R>",
            visible_text(call.kwargs["view"]),
        )

    async def test_worst_case_poll_with_long_names_sources_and_unicode_fits_v2_limits(
        self,
    ):
        self.app.catalog.merge_units([{"id": "daki", "name": "*" * 150, "aliases": []}])
        proposal = self.propose()
        proposal["mode"] = "casual"
        detail = proposal["details"]["daki"]
        detail.update(reason="😀" * 700, conditions="😀" * 300, caveat="😀" * 300)
        detail["sources"] = [
            {
                "quote": "*" * 600,
                "url": "https://animeadventures.fandom.com/wiki/"
                + "a" * 500
                + "?oldid=123",
            }
        ] * 2
        self.app.ui_theme.available = set(ICONS)
        data = payload(
            bot=self.app,
            embed=poll_embed(self.app.store, self.app.catalog, proposal),
            view=PollView(self.app),
        )
        self.assertLessEqual(data["view"].total_children_count, 40)
        self.assertLessEqual(
            len(visible_text(data["view"]).encode("utf-16-le")) // 2, 4000
        )

    async def test_error_response_does_not_expose_internal_exception(self):
        i = self.interaction()
        view = Card(text="Painel")
        await view.on_error(i, RuntimeError("internal-secret-value"), None)
        self.assertNotIn(
            "internal-secret-value",
            visible_text(i.response.send_message.await_args.kwargs["view"]),
        )
