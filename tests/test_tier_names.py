"""Exact form coverage and both quote styles in the Wiki's identity module."""

import unittest

from community_domain import Catalog, ROOT
from tier_catalog import TierCatalog
from tier_names import parse_names


class IdentityCoverageCase(unittest.TestCase):
    def test_quote_styles_preserve_names_without_reading_comments_or_expressions(self):
        text = """return {
 ["Blood (Unleashed)"] = {name ='power_evolved', ChBox_Text_Style="Fz(77%)"},
 ['Hero (Final)'] = {name ="hero_evolved"},
 ["Maker's Guard"] = {name ='guard'},
 -- ["Comment"] = {name="comment"},
 ["Expression"] = {name="hero" .. "_fake"},
 ["Mixed quotes"] = {name='bad"},
}"""
        self.assertEqual(
            parse_names(text),
            [
                ("Blood (Unleashed)", "power_evolved"),
                ("Hero (Final)", "hero_evolved"),
                ("Maker's Guard", "guard"),
            ],
        )

    def test_all_six_previously_skipped_forms_are_in_the_historical_catalogue(self):
        catalog, active = Catalog(), TierCatalog()
        expected = {
            "geten": "Ice Shaper",
            "sonic": "Supersound",
            "tatsumaki": "Tamiki",
            "himeno_evolved": "Ghosty (Sacrifice)",
            "power_evolved": "Blood (Unleashed)",
            "kobeni_evolved": "Cowardly (Scared)",
        }
        for uid, name in expected.items():
            self.assertEqual(catalog.resolve(name).id, uid)
        self.assertNotIn("geten", active.units)
        self.assertTrue((set(expected) - {"geten"}) <= active.units.keys())
        declared = {
            uid
            for _, uid in parse_names((ROOT / "docs/sources/46960.wiki").read_text())
        }
        self.assertEqual(declared, set(catalog.units))

    def test_verified_old_names_do_not_mix_base_and_evolved_forms(self):
        catalog = TierCatalog()
        for name, uid in (
            ("Daky", "daki"),
            ("Daky (Obi)", "daki_evolved"),
            ("Kiroto (Dual)", "kirito_evolved"),
            ("Albedo (Overseer)", "albedo_evolved"),
        ):
            self.assertEqual(catalog.resolve(name).id, uid)
        self.assertEqual(
            catalog.mentions("Daky (Obi) tem mais sangramento no infinito."),
            {"daki_evolved"},
        )
        with self.assertRaises(ValueError):
            catalog.resolve("Luffo (Gear IV)")
