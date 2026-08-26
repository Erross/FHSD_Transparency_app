import unittest

from scripts.ingest import validate_export_target
from scripts.route_snapshot import resolve_target


SCHOOL = {
    "id": "school-watchlist",
    "displayName": "School Watchlist",
    "sourceUrls": ["https://www.facebook.com/profile.php?id=111"],
    "authorAliases": ["School Watchlist"],
    "filenameAliases": ["School_Watchlist"],
}
OTHER = {
    "id": "other-page",
    "displayName": "Other Page",
    "sourceUrls": ["https://www.facebook.com/profile.php?id=222"],
    "authorAliases": ["Other Page"],
    "filenameAliases": ["Other_Page"],
}
CONFIGS = [SCHOOL, OTHER]


class SnapshotRoutingTests(unittest.TestCase):
    def test_legacy_page_context_routes_without_target_folder(self):
        payload = {
            "targetAuthor": "School Watchlist",
            "items": [{"pageUrl": "https://www.facebook.com/profile.php?id=111"}],
        }
        result = resolve_target(payload, "random-export-name.json", CONFIGS)
        self.assertTrue(result["ok"])
        self.assertEqual("school-watchlist", result["targetId"])
        self.assertEqual("page_profile_id", result["method"])

    def test_incidental_item_profile_ids_do_not_create_false_multi_target_match(self):
        payload = {
            "targetAuthor": "School Watchlist",
            "items": [
                {
                    "itemType": "post",
                    "pageUrl": "https://www.facebook.com/profile.php?id=111",
                    "profileId": "111",
                },
                {
                    "itemType": "comment",
                    "pageUrl": "https://www.facebook.com/permalink.php?story_fbid=abc&id=111",
                    "profileId": "222",
                },
                {
                    "itemType": "comment",
                    "pageUrl": "https://www.facebook.com/permalink.php?story_fbid=abc&id=111",
                    "profileId": "999999",
                },
            ],
        }
        result = resolve_target(payload, "facebook-visible-export-123.json", CONFIGS)
        self.assertTrue(result["ok"])
        self.assertEqual("school-watchlist", result["targetId"])
        self.assertEqual(["111"], result["observedProfileIds"])

    def test_v10_top_level_target_profile_routes(self):
        payload = {
            "target": {
                "displayName": "School Watchlist",
                "profileId": "111",
                "sourceUrl": "https://www.facebook.com/profile.php?id=111",
            },
            "items": [],
        }
        result = resolve_target(payload, "School_Watchlist_2026-08-26.json", CONFIGS)
        self.assertTrue(result["ok"])
        self.assertEqual("school-watchlist", result["targetId"])
        validation = validate_export_target(SCHOOL, payload)
        self.assertTrue(validation["completeEligible"])

    def test_filename_alias_is_safe_fallback(self):
        result = resolve_target(
            {"items": []},
            "School_Watchlist_2024-01-01_2026-08-26_10-48-39.json",
            CONFIGS,
        )
        self.assertTrue(result["ok"])
        self.assertEqual("school-watchlist", result["targetId"])
        self.assertEqual("filename_alias", result["method"])

    def test_filename_conflict_with_page_context_is_rejected(self):
        payload = {
            "targetAuthor": "School Watchlist",
            "items": [{"pageUrl": "https://www.facebook.com/profile.php?id=111"}],
        }
        result = resolve_target(payload, "Other_Page_2026-08-26.json", CONFIGS)
        self.assertFalse(result["ok"])
        self.assertIn("Filename suggests", result["reason"])

    def test_unknown_target_is_rejected(self):
        result = resolve_target({"targetAuthor": "Mystery Page", "items": []}, "mystery.json", CONFIGS)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
