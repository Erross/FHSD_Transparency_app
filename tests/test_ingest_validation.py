import unittest

from scripts.ingest import validate_export_target

CONFIG = {
    "id": "school-watchlist",
    "displayName": "School Watchlist",
    "authorAliases": ["School Watchlist", "FHSD School Watchlist"],
    "sourceUrls": ["https://www.facebook.com/profile.php?id=61581121856469"],
}


class ValidationTests(unittest.TestCase):
    def test_matching_export_is_complete_eligible(self):
        payload = {
            "targetAuthor": "School Watchlist",
            "items": [{"pageUrl": "https://www.facebook.com/profile.php?id=61581121856469"}],
        }
        result = validate_export_target(CONFIG, payload)
        self.assertTrue(result["completeEligible"])
        self.assertEqual([], result["warnings"])

    def test_mislabeled_export_is_partial_only_even_if_page_url_matches(self):
        payload = {
            "targetAuthor": "Greenwood for FHSD School Board",
            "items": [{"pageUrl": "https://www.facebook.com/profile.php?id=61581121856469"}],
        }
        result = validate_export_target(CONFIG, payload)
        self.assertFalse(result["completeEligible"])
        self.assertTrue(result["sourceProfileMatches"])
        self.assertFalse(result["declaredTargetMatches"])
        self.assertEqual("declared_target_mismatch", result["warnings"][0]["code"])


if __name__ == "__main__":
    unittest.main()
