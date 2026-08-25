import unittest

from scripts.core import initial_state, normalize_item
from scripts.coverage import apply_coverage_snapshot, declared_date_window, resolve_content_date

CONFIG = {
    "crawl": {
        "bulkMissingAbsoluteThreshold": 2,
        "bulkMissingRatioThreshold": 0.25,
        "bulkThreadMissingAbsoluteThreshold": 2,
    }
}


def comment(comment_id, text, exact="", relative="", captured="2026-08-25T17:31:58Z", post_id="p1"):
    return {
        "itemType": "comment",
        "author": "Commenter",
        "commentId": comment_id,
        "postId": post_id,
        "bodyText": text,
        "timestampExact": exact,
        "timestampText": relative,
        "capturedAt": captured,
        "permalink": f"https://facebook.example/post/{post_id}?comment_id={comment_id}",
    }


def post(post_id, text, exact="", relative="", captured="2026-08-25T17:31:58Z"):
    return {
        "itemType": "post",
        "author": "School Watchlist",
        "postId": post_id,
        "bodyText": text,
        "timestampExact": exact,
        "timestampText": relative,
        "capturedAt": captured,
        "permalink": f"https://facebook.example/post/{post_id}",
    }


class CoverageTests(unittest.TestCase):
    def apply(self, state, items, when, cutoff, complete=True):
        return apply_coverage_snapshot(
            state,
            [normalize_item(item, when) for item in items],
            observed_at=when,
            snapshot_meta={"collectionLimit": {"mode": "date", "cutoffDate": cutoff}},
            complete=complete,
            target_config=CONFIG,
        )

    def test_facebook_exact_date(self):
        value, quality = resolve_content_date({"timestampExact": "Tuesday 25 August 2026 at 16:41"})
        self.assertEqual("2026-08-25", value.isoformat())
        self.assertEqual("exact", quality)

    def test_relative_date_uses_capture_time(self):
        value, quality = resolve_content_date({"timestampText": "1w", "capturedAt": "2026-08-25T21:50:51Z"})
        self.assertEqual("2026-08-18", value.isoformat())
        self.assertEqual("relative", quality)

    def test_declared_window(self):
        window = declared_date_window(
            {"collectionLimit": {"mode": "date", "cutoffDate": "2026-06-01"}},
            "2026-08-25T21:51:38Z",
        )
        self.assertEqual("2026-06-01", window[0].isoformat())
        self.assertEqual("2026-08-25", window[1].isoformat())

    def test_only_in_window_posts_can_become_missing(self):
        state = initial_state("school-watchlist")
        state = self.apply(
            state,
            [
                post("in", "inside", exact="Monday 24 August 2026 at 18:40"),
                post("old", "outside", exact="24 May 2026"),
                post("unknown", "unknown date"),
            ],
            "2026-08-25T17:31:58Z",
            "2024-01-25",
        )
        state = self.apply(state, [], "2026-08-25T21:51:38Z", "2026-06-01")
        self.assertEqual("missing_once", state["entities"]["post:in"]["status"])
        self.assertEqual("active", state["entities"]["post:old"]["status"])
        self.assertEqual("active", state["entities"]["post:unknown"]["status"])
        snapshot = state["snapshots"][-1]
        self.assertEqual(1, snapshot["coverageEligiblePriorPosts"])
        self.assertEqual(1, snapshot["coverageUnknownDatePriorPosts"])
        self.assertEqual(1, snapshot["coverageOutsidePriorPosts"])

    def test_comment_missing_requires_parent_post_to_be_revisited(self):
        state = initial_state("school-watchlist")
        state = self.apply(
            state,
            [
                post("p1", "post", exact="24 August 2026"),
                comment("c1", "critical comment", exact="24 August 2026", post_id="p1"),
            ],
            "2026-08-25T17:31:58Z",
            "2024-01-25",
        )
        state = self.apply(
            state,
            [post("p1", "post", exact="24 August 2026")],
            "2026-08-25T21:51:38Z",
            "2026-06-01",
        )
        self.assertEqual("missing_once", state["entities"]["comment:c1"]["status"])
        self.assertEqual(1, state["snapshots"][-1]["coverageEligibleCommentsByObservedParent"])

    def test_recent_comment_on_unvisited_parent_is_deferred(self):
        state = initial_state("school-watchlist")
        state = self.apply(
            state,
            [
                post("oldpost", "old post", exact="24 May 2026"),
                comment("recent", "new comment on old post", exact="24 August 2026", post_id="oldpost"),
            ],
            "2026-08-25T17:31:58Z",
            "2024-01-25",
        )
        state = self.apply(state, [], "2026-08-25T21:51:38Z", "2026-06-01")
        self.assertEqual("active", state["entities"]["comment:recent"]["status"])
        self.assertEqual(1, state["snapshots"][-1]["coverageDeferredCommentsParentNotObserved"])

    def test_partial_snapshot_never_marks_missing_even_with_date_limit(self):
        state = initial_state("school-watchlist")
        state = self.apply(
            state,
            [post("p1", "post", exact="24 August 2026"), comment("c1", "inside", post_id="p1")],
            "2026-08-25T17:31:58Z",
            "2024-01-25",
        )
        state = self.apply(
            state,
            [post("p1", "post", exact="24 August 2026")],
            "2026-08-25T21:51:38Z",
            "2026-06-01",
            complete=False,
        )
        self.assertEqual("active", state["entities"]["comment:c1"]["status"])


if __name__ == "__main__":
    unittest.main()
