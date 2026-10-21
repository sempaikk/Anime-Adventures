import hashlib
import json
import random
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from quiz_content import DATA_FILE, QuestionDeck, load_pack, normalize_answer

PACK = load_pack()
QUESTIONS = {q.id: q for q in PACK.questions}


class ContentTests(unittest.TestCase):
    def test_release_roster_and_coverage(self):
        self.assertEqual(Counter(u['rarity'] for u in PACK.units), {'Rare': 18, 'Epic': 10, 'Legendary': 9, 'Mythic': 7})
        self.assertGreaterEqual(len(PACK.questions), 2000)
        self.assertEqual(len({q.category for q in PACK.questions}), 14)
        self.assertEqual(len([q for q in PACK.questions if q.category == 'Evoluções']), 4)
        self.assertEqual(len([q for q in PACK.questions if q.id.startswith('act:')]), 24)
        self.assertEqual(len([q for q in PACK.questions if q.id.startswith('act-position:')]), 24)

    def test_later_and_undated_forms_are_not_activated(self):
        ids = {u['id'] for u in PACK.units}
        self.assertFalse(ids & {'lelouch', 'lelouch_evolved', 'bulma', 'frieza', 'killua', 'todoroki', 'ichigo_masked'})
        self.assertFalse(any('eren_evolved' in q.id or 'rengoku_evolved' in q.id for q in PACK.questions))
        self.assertNotIn('boss:4:4', QUESTIONS)
        self.assertFalse(any('Joker' in q.prompt or 'Relic' in q.prompt for q in PACK.questions))

    def test_historical_values_have_not_been_replaced_with_modern_values(self):
        self.assertTrue(QUESTIONS['food:Wisteria Flower:xp'].accepts('115 XP'))
        self.assertTrue(QUESTIONS['summon:cost'].accepts('50 gemas'))
        self.assertTrue(QUESTIONS['stats:madara:cost'].accepts('1400 Yen'))
        self.assertTrue(QUESTIONS['rarity:speedwagon'].accepts('épico'))
        self.assertFalse(QUESTIONS['rarity:speedwagon'].accepts('Secret'))

    def test_exact_answers_and_documented_aliases(self):
        for unit in PACK.units:
            q = QUESTIONS.get('unit:' + unit['id'])
            if q is None:
                self.assertIn('rarity:' + unit['id'], QUESTIONS)
                continue
            for name in [unit['character'], unit['game_name'], unit.get('historical_name'), *unit['aliases']]:
                if name:
                    self.assertTrue(q.accepts(name), (unit['id'], name))
        self.assertTrue(QUESTIONS['unit:armin'].accepts('ARMEIN'))
        self.assertTrue(QUESTIONS['unit:armin'].accepts('Arlem'))
        self.assertTrue(QUESTIONS['unit:armin'].accepts('Armin Arlert'))
        self.assertTrue(QUESTIONS['unit:speedwagon'].accepts('CEO'))
        self.assertFalse(QUESTIONS['unit:armin'].accepts('Armim'))
        self.assertFalse(QUESTIONS['unit:levi'].accepts('Lex Akoman'))
        self.assertFalse(QUESTIONS['summon:cost'].accepts('acho que são 50'))
        self.assertFalse(QUESTIONS['summon:cost'].accepts(''))

    def test_evolved_answers_require_the_evolved_form(self):
        q = QUESTIONS['evolution:broly_evolved']
        self.assertTrue(q.accepts('Legendary Brulo'))
        self.assertTrue(q.accepts('Super Bro'))
        self.assertFalse(q.accepts('Broly'))
        self.assertFalse(q.accepts('Brulo'))

    def test_boss_aliases_accept_game_and_anime_names_without_merging_forms(self):
        for key, old, anime in [('boss:1:1', 'Zarbo', 'Zarbon'), ('boss:1:6', 'Freezo', 'Frieza'),
                                ('boss:3:2', 'Zui', 'Rui'), ('boss:4:2', 'Kizume', 'Kisame')]:
            q = QUESTIONS[key]
            self.assertTrue(q.accepts(old))
            self.assertTrue(q.accepts(anime))
            self.assertIn('boss_names', q.alias_sources)
            self.assertNotIn('boss_names', q.sources)
        final = QUESTIONS['boss:1:6:form']
        self.assertTrue(final.accepts('Freezo (Final)'))
        self.assertTrue(final.accepts('Frieza (Final)'))
        self.assertFalse(final.accepts('Frieza'))
        self.assertFalse(QUESTIONS['boss:1:6'].accepts('Frieza (Final)'))

    def test_every_choice_question_has_exactly_one_correct_option(self):
        for q in PACK.questions:
            if q.options:
                self.assertEqual(len(q.options), 3, q.id)
                self.assertEqual(len({normalize_answer(o) for o in q.options}), 3, q.id)
                self.assertEqual(sum(q.accepts(o) for o in q.options), 1, q.id)
                self.assertTrue(all(len(o) <= 80 for o in q.options), q.id)

    def test_visual_identification_has_no_anime_biography_riddle(self):
        raw = json.loads(DATA_FILE.read_text())
        self.assertTrue(all('hint' not in unit for unit in raw['units']))
        for q in PACK.questions:
            if q.id.startswith('unit:'):
                self.assertTrue(q.requires_image)
                self.assertIn('forma base', q.prompt)
            self.assertFalse(q.id.startswith('world:') and q.id.endswith(':anime'))

    def test_release_resource_practice_calculations(self):
        for key, answer in [('practice:food:Wisteria Flower:20', '2300 XP'),
                             ('practice:food-mix:Senzu Beans:Ramen:2:3', '800 XP'),
                             ('practice:summon:cost:10', '500 Gems'),
                             ('practice:summon:vip:10', '400 Gems'),
                             ('practice:summon:pity:49', '1'), ('practice:time:2', '6 Gems')]:
            self.assertTrue(QUESTIONS[key].accepts(answer), key)
        self.assertIn('5min', QUESTIONS['practice:time:2'].prompt)
        self.assertIn('sem VIP nem Premium', QUESTIONS['practice:time:2'].prompt)

    def test_comparison_questions_follow_the_sourced_rarity_order(self):
        units = {u['id']: u for u in PACK.units}
        ranks = {'Rare': 0, 'Epic': 1, 'Legendary': 2, 'Mythic': 3}
        labels = {'Rare': 'Rara', 'Epic': 'Épica', 'Legendary': 'Lendária', 'Mythic': 'Mítica'}
        for q in PACK.questions:
            if q.id.startswith('compare:rarity:'):
                a, b = [units[key] for key in q.id.split(':')[2:]]
                expected = 'Mesma raridade' if a['rarity'] == b['rarity'] else max((a, b), key=lambda u: ranks[u['rarity']])['game_name']
                self.assertTrue(q.accepts(expected), q.id)
            if q.id.startswith('team:rarity:'):
                group = [units[key] for key in q.id.split(':')[2:]]
                self.assertEqual(len({u['id'] for u in group}), 3)
                expected = max(group, key=lambda u: ranks[u['rarity']])['rarity']
                self.assertTrue(q.accepts(labels[expected]), q.id)

    def test_large_rarity_pool_does_not_dominate_the_first_rounds(self):
        deck = QuestionDeck(PACK.questions, random.Random(2))
        draws = [deck.draw() for _ in range(100)]
        self.assertGreaterEqual(len({q.category for q in draws}), 12)
        self.assertLess(sum(q.category == 'Raridades' for q in draws), 20)
        self.assertEqual(len({q.id for q in draws}), 100)

    def test_normalization_keeps_exact_words(self):
        self.assertEqual(normalize_answer('  MÍTICA_ÉPICA-test! '), 'mitica epica test')
        self.assertNotEqual(normalize_answer('prime force'), normalize_answer('primeforce'))

    def test_additional_gameplay_questions_match_the_archived_release_facts(self):
        for key, expected in [('stats:josuke:total', '6.150 Yen'),
                              ('ability-owner:madara:7', 'Madara'), ('ability-level:ichigo:4', 'Upgrade 4'),
                              ('trait-effect:Golden', 'Aumentar o dinheiro gerado'),
                              ('world-route:next:1', 'Shiganshinu District'),
                              ('quest-scope:Damage I', 'Qualquer modo'),
                              ('store-value:Unit Storage', '100'), ('sell-refund:madara', '350 Yen')]:
            self.assertTrue(QUESTIONS[key].accepts(expected), key)
        for q in PACK.questions:
            if q.id.startswith('act-position:'):
                world, act = q.id.split(':')[1:]
                original = QUESTIONS[f'act:{world}:{act}']
                self.assertIn(original.answer, q.prompt)
                self.assertTrue(q.accepts('Ato ' + act))

    def test_original_source_snapshots_match_recorded_hashes(self):
        root = DATA_FILE.parent.parent
        snapshots = 0
        for source in PACK.sources.values():
            self.assertTrue(source['url'].startswith('https://animeadventures.fandom.com/'))
            if 'snapshot' in source:
                snapshots += 1
                self.assertEqual(hashlib.sha256((root / source['snapshot']).read_bytes()).hexdigest(), source['sha256'])
        self.assertGreaterEqual(snapshots, 19)

    def test_source_usage_does_not_promote_identity_pages_to_historical_stats(self):
        for q in PACK.questions:
            if not q.id.startswith('unit:'):
                self.assertTrue(all(PACK.sources[s]['kind'] != 'identity_only' for s in q.sources if s != 'names'), q.id)
            self.assertGreater(len(q.accepted), 0)
            self.assertTrue(all(q.accepts(a) for a in q.accepted))

    def test_deck_exhaustion_and_boundary(self):
        deck = QuestionDeck(PACK.questions, random.Random(85))
        for _ in range(3):
            cycle = [deck.draw().id for _ in PACK.questions]
            self.assertEqual(len(set(cycle)), len(PACK.questions))
            if 'previous' in locals():
                self.assertNotEqual(previous, cycle[0])
            previous = cycle[-1]

    def test_small_deck_avoids_same_subject_or_category_when_possible(self):
        subset = (QUESTIONS['unit:armin'], QUESTIONS['trait:Nimble'], QUESTIONS['summon:cost'])
        deck = QuestionDeck(subset, random.Random(10))
        draws = [deck.draw() for _ in range(20)]
        self.assertTrue(all(a.id != b.id for a, b in zip(draws, draws[1:])))
        single = QuestionDeck(subset[:1])
        self.assertEqual(single.draw(), single.draw())

    def test_corrupt_or_wrong_stage_bank_fails_closed(self):
        data = json.loads(DATA_FILE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.json'
            for mutate in [lambda d: d.update(stage='update_1'), lambda d: d['questions'][0].update(sources=['missing']), lambda d: d['questions'].append(d['questions'][0]), lambda d: d['sources']['roster'].update(url='http://bad.example/'), lambda d: d['questions'][0].update(alias_sources=['missing'])]:
                candidate = json.loads(json.dumps(data))
                mutate(candidate)
                path.write_text(json.dumps(candidate))
                with self.assertRaises(ValueError):
                    load_pack(path)
