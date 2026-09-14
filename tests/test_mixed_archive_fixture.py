import unittest
from collections import Counter
from pathlib import Path

from scripts.io_utils import read_json
from scripts.ownership import split_obvious_foreign_target_items
from scripts.route_snapshot import load_target_configs


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "archive" / "school-watchlist" / "raw" / "2026-09-13T20-58-33.066Z-09cc03cf8482.json.gz"


class MixedArchiveFixtureTests(unittest.TestCase):
    def test_sep13_raw_contains_and_partitions_blair_posts(self):
        payload = read_json(RAW)
        items = payload.get("items", [])
        post_authors = Counter(
            str(item.get("authorDisplayName") or item.get("author") or "")
            for item in items
            if isinstance(item, dict) and str(item.get("itemType") or "").casefold() == "post"
        )
        self.assertEqual(payload.get("itemCount"), 1164)
        self.assertGreater(post_authors["Steven Blair For Francis Howell School Board"], 0, post_authors)

        configs = load_target_configs(ROOT)
        sw = next(config for config in configs if config.get("id") == "school-watchlist")
        kept, foreign, diagnostics = split_obvious_foreign_target_items(items, sw, configs)
        self.assertGreater(len(foreign), 0, {"authors": post_authors, "diagnostics": diagnostics})
        self.assertGreater(
            diagnostics.get("foreignByTarget", {}).get("steven-blair-for-francis-howell-school-board", 0),
            0,
            {"authors": post_authors, "diagnostics": diagnostics},
        )
        self.assertEqual(len(kept) + len(foreign), len([item for item in items if isinstance(item, dict)]))


if __name__ == "__main__":
    unittest.main()
