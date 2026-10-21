import hashlib
import unittest
from pathlib import Path

import quiz_media as media
from quiz_content import load_pack

PACK = load_pack()
QUESTIONS = {q.id: q for q in PACK.questions}


class MediaTests(unittest.TestCase):
    def test_assets_are_reviewed_wiki_or_user_images_with_matching_hashes(self):
        self.assertGreaterEqual(len(media.MEDIA['assets']), 30)
        for asset in media.MEDIA['assets'].values():
            path = media.ROOT / asset['path']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), asset['sha256'])
            self.assertIn(asset['kind'], ('wiki', 'user_provided'))
            self.assertFalse(asset['processing']['generation'])
            self.assertNotIn('quiz-portal', asset['path'])
            if asset['kind'] == 'wiki':
                self.assertTrue(asset['source_page'].startswith('https://animeadventures.fandom.com/wiki/'))
            else:
                self.assertIn('approval', asset)

    def test_identity_question_never_shows_unit_image_until_answer(self):
        for q in PACK.questions:
            if q.id.startswith('unit:'):
                self.assertIsNone(media.for_question(q), q.id)
        revealed = media.for_question(QUESTIONS['unit:broly'], revealed=True)
        self.assertIsNotNone(revealed)
        self.assertEqual(revealed['form'], 'base')

    def test_evolution_shows_named_base_before_and_correct_evolved_form_after(self):
        q = QUESTIONS['evolution:broly_evolved']
        before = media.for_question(q)
        after = media.for_question(q, revealed=True)
        self.assertEqual(before['form'], 'base')
        self.assertEqual(after['form'], 'evolved')
        self.assertNotEqual(before['path'], after['path'])
        self.assertIn('Super_Bro', after['source_page'])

    def test_missing_evolved_portrait_is_not_replaced_with_base_or_placeholder(self):
        q = QUESTIONS['evolution:all_might_evolved']
        self.assertIsNotNone(media.for_question(q))
        self.assertIsNone(media.for_question(q, revealed=True))

    def test_rarity_and_upgrade_questions_can_illustrate_the_named_character(self):
        self.assertEqual(media.for_question(QUESTIONS['rarity:broly'])['form'], 'base')
        self.assertEqual(media.for_question(QUESTIONS['stats:madara:cost'])['form'], 'base')
        # No character is substituted for an unavailable portrait.
        self.assertIsNone(media.for_question(QUESTIONS['rarity:itachi']))

    def test_world_and_food_identification_hide_their_answer_image(self):
        self.assertIsNone(media.for_question(QUESTIONS['world:1:order']))
        self.assertIsNone(media.for_question(QUESTIONS['food:Senzu Beans:name']))
        self.assertIsNotNone(media.for_question(QUESTIONS['food:Senzu Beans:xp']))
        self.assertIsNotNone(media.for_question(QUESTIONS['boss:1:1']))
        self.assertIsNotNone(media.for_question(QUESTIONS['world:1:order'], revealed=True))

    def test_banners_are_the_two_user_supplied_originals(self):
        self.assertEqual(len(media.MEDIA['banners']), 2)
        for index, original in [(0, 'user_banner_1'), (1, 'user_banner_2')]:
            banner = media.banner(index)
            self.assertEqual(banner['source_file'], original)
            self.assertFalse(banner['processing']['generation'])
            self.assertEqual(banner['sha256'], banner['original_sha256'])
            self.assertTrue(banner['url'].startswith(media.PUBLIC_ASSETS))
