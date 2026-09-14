import unittest

from scripts.ownership import split_obvious_foreign_target_items


class OwnershipSplitTests(unittest.TestCase):
    def setUp(self):
        self.school_watchlist = {
            "id": "school-watchlist",
            "displayName": "School Watchlist",
            "authorAliases": ["School Watchlist", "FHSD School Watchlist"],
            "sourceUrls": ["https://www.facebook.com/profile.php?id=61581121856469"],
        }
        self.blair = {
            "id": "steven-blair-for-francis-howell-school-board",
            "displayName": "Steven Blair For Francis Howell School Board",
            "authorAliases": ["Steven Blair For Francis Howell School Board"],
            "sourceUrls": [
                "https://www.facebook.com/profile.php?id=61550067735304",
                "https://www.facebook.com/StevenBlairForFrancisHowellSchoolBoard",
            ],
        }
        self.configs = [self.school_watchlist, self.blair]

    def test_foreign_blair_post_and_bound_comment_are_split(self):
        items = [
            {
                "itemType": "post",
                "author": "Steven Blair For Francis Howell School Board",
                "postId": "122318760038002257",
                "pageUrl": "https://www.facebook.com/StevenBlairForFrancisHowellSchoolBoard",
                "dateEvidence": {"ownerId": "61550067735304"},
            },
            {
                "itemType": "comment",
                "author": "Jane Citizen",
                "commentId": "c1",
                "parentPostId": "122318760038002257",
                "pageUrl": "https://www.facebook.com/StevenBlairForFrancisHowellSchoolBoard/posts/pfbid123",
            },
            {
                "itemType": "post",
                "author": "School Watchlist",
                "postId": "sw1",
                "pageUrl": "https://www.facebook.com/profile.php?id=61581121856469",
            },
        ]
        kept, foreign, diagnostics = split_obvious_foreign_target_items(items, self.school_watchlist, self.configs)
        self.assertEqual([item.get("postId") for item in kept if item.get("itemType") == "post"], ["sw1"])
        self.assertEqual(len(foreign), 2)
        self.assertEqual(diagnostics["foreignByTarget"].get(self.blair["id"]), 2)

    def test_blair_named_commenter_on_school_watchlist_is_not_split(self):
        items = [
            {
                "itemType": "comment",
                "author": "Steven Blair For Francis Howell School Board",
                "commentId": "c2",
                "parentPostId": "sw1",
                "pageUrl": "https://www.facebook.com/profile.php?id=61581121856469",
            }
        ]
        kept, foreign, _ = split_obvious_foreign_target_items(items, self.school_watchlist, self.configs)
        self.assertEqual(len(kept), 1)
        self.assertEqual(foreign, [])

    def test_shared_source_does_not_override_school_watchlist_wrapper(self):
        items = [
            {
                "itemType": "post",
                "author": "School Watchlist",
                "sharedAuthor": "Steven Blair For Francis Howell School Board",
                "postId": "sw-shared-1",
                "pageUrl": "https://www.facebook.com/profile.php?id=61581121856469",
                "sharedPermalink": "https://www.facebook.com/StevenBlairForFrancisHowellSchoolBoard/posts/pfbid123",
            }
        ]
        kept, foreign, _ = split_obvious_foreign_target_items(items, self.school_watchlist, self.configs)
        self.assertEqual(len(kept), 1)
        self.assertEqual(foreign, [])


if __name__ == "__main__":
    unittest.main()
