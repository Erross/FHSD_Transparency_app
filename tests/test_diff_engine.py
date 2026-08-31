import unittest

from scripts.core import apply_snapshot, initial_state, normalize_item

CONFIG = {
    "crawl": {
        "requiresCompleteSnapshotForMissing": True,
        "missingRecheckThreshold": 2,
        "bulkMissingAbsoluteThreshold": 2,
        "bulkMissingRatioThreshold": 0.25,
        "bulkThreadMissingAbsoluteThreshold": 2,
    }
}


def post(post_id, text):
    return {
        "itemType": "post",
        "author": "School Watchlist",
        "postId": post_id,
        "bodyText": text,
        "permalink": f"https://facebook.example/post/{post_id}",
    }


def comment(comment_id, text, post_id="p1"):
    return {
        "itemType": "comment",
        "author": "Commenter",
        "commentId": comment_id,
        "postId": post_id,
        "bodyText": text,
        "permalink": f"https://facebook.example/post/{post_id}?comment_id={comment_id}",
    }


class DiffEngineTests(unittest.TestCase):
    def apply(self, state, items, when, complete=False):
        return apply_snapshot(
            state,
            [normalize_item(item, when) for item in items],
            observed_at=when,
            snapshot_meta={"rawSha256": when},
            complete=complete,
            target_config=CONFIG,
        )

    def test_stable_identity_and_parent_link(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "hello"), comment("c1", "world")], "t1")
        self.assertIn("post:p1", state["entities"])
        self.assertIn("comment:c1", state["entities"])
        self.assertEqual("post:p1", state["entities"]["comment:c1"]["parentId"])
        self.assertEqual("strong", state["entities"]["comment:c1"]["identityQuality"])

    def test_first_snapshot_is_baseline_not_change_flood(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "one"), comment("c1", "a")], "t1", complete=True)
        self.assertTrue(state["snapshots"][0]["baseline"])
        self.assertEqual([], state["events"])
        state = self.apply(state, [post("p1", "one"), comment("c1", "a"), comment("c2", "new")], "t2", complete=True)
        self.assertEqual("new", state["events"][-1]["type"])

    def test_edit_creates_version_and_event(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "first")], "t1")
        state = self.apply(state, [post("p1", "second")], "t2")
        entity = state["entities"]["post:p1"]
        self.assertEqual(2, len(entity["versions"]))
        self.assertEqual("second", entity["text"])
        self.assertEqual("edited", state["events"][-1]["type"])
        self.assertEqual("first", state["events"][-1]["beforeText"])

    def test_comment_ui_chrome_does_not_create_false_edit(self):
        first = comment("c1", "17h · by authorMaster schedules are hard.LikeReply8")
        later = comment("c1", "22h · by authorMaster schedules are hard.LikeReply9")
        state = self.apply(initial_state("school-watchlist"), [post("p1", "one"), first], "t1")
        state = self.apply(state, [post("p1", "one"), later], "t2")
        entity = state["entities"]["comment:c1"]
        self.assertEqual("Master schedules are hard.", entity["text"])
        self.assertEqual(1, len(entity["versions"]))
        self.assertFalse(any(e["type"] == "edited" for e in state["events"]))

    def test_collapsed_see_more_does_not_create_false_edit(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "A long post with details See less")], "t1")
        state = self.apply(state, [post("p1", "A long post… See more")], "t2")
        entity = state["entities"]["post:p1"]
        self.assertEqual("A long post with details", entity["text"])
        self.assertEqual(1, len(entity["versions"]))
        self.assertFalse(any(e["type"] == "edited" for e in state["events"]))

    def test_comment_parent_id_change_creates_post_alias_not_duplicate_thread(self):
        state = self.apply(initial_state("school-watchlist"), [post("old", "schedule"), comment("c1", "same", "old")], "t1")
        state = self.apply(state, [post("new", "schedule"), comment("c1", "same", "new")], "t2")
        self.assertIn("post:old", state["entities"])
        self.assertNotIn("post:new", state["entities"])
        self.assertEqual("post:old", state["entities"]["comment:c1"]["parentId"])
        self.assertIn("new", state["entities"]["comment:c1"]["postIdAliases"])
        self.assertEqual(1, state["snapshots"][-1]["postAliasCount"])

    def test_incomplete_snapshot_never_marks_missing(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "one"), post("p2", "two")], "t1", complete=True)
        state = self.apply(state, [post("p1", "one")], "t2", complete=False)
        self.assertEqual("active", state["entities"]["post:p2"]["status"])
        self.assertEqual(0, state["entities"]["post:p2"]["missingCount"])

    def test_complete_snapshots_progress_missing_state_and_reappear(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "one"), post("p2", "two")], "t1", complete=True)
        state = self.apply(state, [post("p1", "one")], "t2", complete=True)
        self.assertEqual("missing_once", state["entities"]["post:p2"]["status"])
        state = self.apply(state, [post("p1", "one")], "t3", complete=True)
        self.assertEqual("missing_recheck", state["entities"]["post:p2"]["status"])
        state = self.apply(state, [post("p1", "one"), post("p2", "two")], "t4", complete=True)
        self.assertEqual("reappeared", state["entities"]["post:p2"]["status"])
        self.assertEqual("reappeared", state["events"][-1]["type"])

    def test_bulk_missing_is_descriptive_not_attributed(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "one"), comment("c1", "a"), comment("c2", "b"), comment("c3", "c")], "t1", complete=True)
        state = self.apply(state, [post("p1", "one")], "t2", complete=True)
        bulk = [event for event in state["events"] if event["type"] == "bulk_missing"]
        self.assertEqual(1, len(bulk))
        self.assertIn("causation is not attributed", bulk[0]["note"])

    def test_thread_bulk_missing_event(self):
        state = self.apply(initial_state("school-watchlist"), [post("p1", "one"), comment("c1", "a"), comment("c2", "b"), comment("c3", "c")], "t1", complete=True)
        state = self.apply(state, [post("p1", "one")], "t2", complete=True)
        thread_events = [event for event in state["events"] if event["type"] == "bulk_missing_thread"]
        self.assertEqual(1, len(thread_events))
        self.assertEqual("post:p1", thread_events[0]["parentId"])
        self.assertIn("causation is not attributed", thread_events[0]["note"])


if __name__ == "__main__":
    unittest.main()
