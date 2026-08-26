import unittest

from scripts.core import normalize_item
from scripts.enrich import enrich_normalized


class EnrichmentTests(unittest.TestCase):
    def test_v9_post_gets_backward_compatible_author_and_date(self):
        raw = {
            "itemType": "post",
            "author": "School Watchlist",
            "profileId": "61581121856469",
            "pageUrl": "https://www.facebook.com/profile.php?id=61581121856469",
            "timestampExact": "18 September 2025",
            "bodyText": "A full post See less",
            "attachmentSummary": "Example | EXAMPLE.COM",
            "imageAlts": ["Example image"],
        }
        observed = "2026-08-26T15:48:39Z"
        enriched = enrich_normalized(raw, normalize_item(raw, observed), observed)
        self.assertEqual(enriched["authorKey"], "facebook:61581121856469")
        self.assertEqual(enriched["publishedDate"], "2025-09-18")
        self.assertTrue(enriched["bodyComplete"])
        self.assertEqual(enriched["attachmentSummary"], "Example | EXAMPLE.COM")

    def test_page_profile_id_unifies_facebook_attribution_variants(self):
        observed = "2026-08-26T15:48:39Z"
        base = {
            "itemType": "post",
            "profileId": "61581121856469",
            "pageUrl": "https://www.facebook.com/profile.php?id=61581121856469",
            "bodyText": "Post body",
        }
        normal = {**base, "author": "School Watchlist", "authorKey": "school watchlist"}
        tagged = {
            **base,
            "author": "School Watchlist is with REAL TALK 93.3FM.",
            "authorKey": "school watchlist is with real talk 93.3fm.",
        }
        a = enrich_normalized(normal, normalize_item(normal, observed), observed)
        b = enrich_normalized(tagged, normalize_item(tagged, observed), observed)
        self.assertEqual(a["authorKey"], "facebook:61581121856469")
        self.assertEqual(b["authorKey"], a["authorKey"])

    def test_truncated_post_is_marked_incomplete(self):
        raw = {"itemType": "post", "author": "School Watchlist", "bodyText": "Long post… See more"}
        observed = "2026-08-26T15:48:39Z"
        enriched = enrich_normalized(raw, normalize_item(raw, observed), observed)
        self.assertFalse(enriched["bodyComplete"])
        self.assertTrue(enriched["hadSeeMore"])
        self.assertEqual(enriched["expansionResult"], "still_truncated")

    def test_v10_fields_win_when_present(self):
        raw = {
            "itemType": "comment",
            "author": "Example Person",
            "authorDisplayName": "Example Person",
            "authorProfileId": "123",
            "authorProfileUrl": "https://www.facebook.com/profile.php?id=123",
            "authorKey": "facebook:123",
            "publishedAt": "2026-08-26T09:30:00-05:00",
            "publishedAtPrecision": "minute",
            "publishedAtSource": "facebook-tooltip",
            "commentId": "456",
            "bodyText": "Comment body",
            "bodyComplete": True,
            "facebookEdited": True,
            "facebookEditedLabel": "Edited",
        }
        observed = "2026-08-26T15:48:39Z"
        enriched = enrich_normalized(raw, normalize_item(raw, observed), observed)
        self.assertEqual(enriched["authorKey"], "facebook:123")
        self.assertEqual(enriched["publishedAtPrecision"], "minute")
        self.assertTrue(enriched["facebookEdited"])


if __name__ == "__main__":
    unittest.main()
