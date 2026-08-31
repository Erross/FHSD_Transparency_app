import unittest

from scripts.build_site import _author_index, _discussion_counts, _latest_delta


class SiteIndexTests(unittest.TestCase):
    def test_author_index_groups_comments(self):
        rows = [
            {"id": "comment:1", "itemType": "comment", "author": "Matt Stolle", "authorKey": "name:matt stolle", "lastSeen": "2026-08-26"},
            {"id": "comment:2", "itemType": "comment", "author": "Matt Stolle", "authorKey": "name:matt stolle", "lastSeen": "2026-08-25"},
        ]
        authors = _author_index(rows)
        self.assertEqual(len(authors), 1)
        self.assertEqual(authors[0]["comments"], 2)
        self.assertEqual(authors[0]["entityIds"], ["comment:1", "comment:2"])

    def test_discussion_count(self):
        rows = [
            {"id": "post:1", "itemType": "post"},
            {"id": "comment:1", "itemType": "comment", "parentId": "post:1"},
            {"id": "comment:2", "itemType": "comment", "parentId": "post:1"},
        ]
        self.assertEqual(_discussion_counts(rows)["post:1"], 2)

    def test_latest_delta_counts_only_latest_snapshot(self):
        snapshots = [{"observedAt": "2026-08-26", "complete": True}, {"observedAt": "2026-08-25", "complete": True}]
        events = [
            {"observedAt": "2026-08-26", "type": "new"},
            {"observedAt": "2026-08-26", "type": "edited"},
            {"observedAt": "2026-08-25", "type": "new"},
        ]
        delta = _latest_delta(events, snapshots)
        self.assertEqual(delta["counts"], {"new": 1, "edited": 1})
        self.assertEqual(delta["previousObservedAt"], "2026-08-25")


if __name__ == "__main__":
    unittest.main()
