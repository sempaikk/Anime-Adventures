"""Private visual scenarios and actual image-content validation."""

import io
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from PIL import Image
import test_tier_thread as fixtures
from community_domain import Catalog
from tier_preview import (
    VisualScenario,
    VisualDemoView,
    check_visual_sequence,
    open_demo,
)


class VisualFramesCase(unittest.TestCase):
    def test_moves_expansion_portrait_change_and_undo_change_actual_pixels(self):
        scenario = VisualScenario(Catalog())
        frames = [scenario.render(n) for n in range(len(scenario.steps))]
        hashes = [f["body_digest"] for f in frames]
        self.assertEqual(len(set(hashes)), 8)
        self.assertEqual(hashes[0], hashes[9])
        self.assertEqual(hashes[5], hashes[7])
        self.assertNotEqual(hashes[5], hashes[6])
        self.assertEqual(frames[5]["ranking"], frames[6]["ranking"])

        def pixels(index, box):
            with Image.open(io.BytesIO(frames[index]["png"])) as image:
                return image.crop(box).tobytes()

        self.assertEqual(pixels(2, (139, 59, 233, 153)), pixels(3, (235, 59, 329, 153)))
        self.assertEqual(
            pixels(3, (139, 59, 233, 153)), pixels(4, (139, 155, 233, 249))
        )
        with (
            Image.open(io.BytesIO(frames[4]["png"])) as before,
            Image.open(io.BytesIO(frames[5]["png"])) as expanded,
        ):
            self.assertGreater(expanded.height, before.height)


class PrivateVisualCase(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ThreadRuntimeCase.asyncSetUp
    asyncTearDown = fixtures.ThreadRuntimeCase.asyncTearDown
    interaction = fixtures.ThreadRuntimeCase.interaction

    async def test_private_view_is_owner_bound_and_does_not_publish_or_rank(self):
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        await open_demo(self.app, i)
        self.assertTrue(i.response.defer.await_args.kwargs["ephemeral"])
        view = i.edit_original_response.await_args.kwargs["view"]
        self.assertIsInstance(view, VisualDemoView)
        self.assertFalse(await view.interaction_check(self.interaction(user=8)))
        with self.assertRaises(ValueError):
            await open_demo(self.app, self.interaction(user=8))
        self.assertEqual(self.env.payloads, [])
        self.assertEqual(self.app.store.latest()["id"], 0)
        self.assertEqual(self.app.media.approved(), {})

    async def test_autoplay_runs_all_steps_without_changing_official_state(self):
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        view = VisualDemoView(self.app, i)
        with patch("tier_preview.asyncio.sleep", new_callable=AsyncMock):
            await view.autoplay.callback(i)
        self.assertEqual(i.edit_original_response.await_count, 10)
        self.assertEqual(view.index, 9)
        self.assertFalse(view.running)
        self.assertEqual(self.app.verification_tasks, set())
        self.assertEqual(self.app.store.latest()["ranking"], [])
        self.assertEqual(self.app.media.approved(), {})

    async def test_discord_returning_another_file_fails_the_visual_check(self):
        received = SimpleNamespace(id=123, attachments=[])

        async def edit(**kwargs):
            file = kwargs["attachments"][0]
            received.attachments = [
                SimpleNamespace(
                    size=len(file.fp.getvalue()),
                    read=AsyncMock(return_value=b"incorrect file"),
                )
            ]

        message = SimpleNamespace(
            id=123,
            edit=AsyncMock(side_effect=edit),
            channel=SimpleNamespace(fetch_message=AsyncMock(return_value=received)),
        )
        with self.assertRaisesRegex(ValueError, "difere da imagem enviada"):
            await check_visual_sequence(self.app, message)
        self.assertEqual(self.app.store.latest()["id"], 0)

    async def test_rapid_navigation_keeps_caption_and_image_on_the_same_stage(self):
        i = self.interaction()
        i.edit_original_response = AsyncMock()
        view = VisualDemoView(self.app, i)
        await asyncio.gather(*(view.next.callback(i) for _ in range(15)))
        self.assertEqual(view.index, 9)
        self.assertIn("10/10", i.edit_original_response.await_args.kwargs["content"])
        self.assertIn(
            "Retornar à grade vazia",
            i.edit_original_response.await_args.kwargs["content"],
        )
        self.assertEqual(self.app.store.latest()["id"], 0)
