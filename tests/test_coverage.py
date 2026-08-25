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
    def test_facebook_exact_date(self):
        value, quality = resolve_content_date(
            {"timestampExact": "Tuesday 25 August 2026 at 16:41"}
        )
        self.assertEqual("2026-08-25", value.isoformat())
        self.assertEqual("exact", quality)

    def test_relative_date_uses_capture_time(self):
        value, quality = resolve_content_date(
            {"timestampText": "1w", "capturedAt": "2026-08-25T21:50:51Z"}
        )
        self.assertEqual("2026-08-18", value.isoformat())
        self.assertEqual("relative", quality)

    def test_declared_window(self):
        window = declared_date_window(
            {"collectionLimit": {"mode": "date", "cutoffDate": "2026-06-01"}},
            "2026-08-25T21:51:38Z",
        )
        self.assertEqual("2026-06-01", window[0].isoformat())
        self.assertEqual("2026-08-25", window[1].isoformat())

    def test_only_in_window_absence_marks_missing(self):
        state = initial_state("school-watchlist")
        baseline = [
            normalize_item(comment("in", "inside", exact="Monday 24 August 2026 at 18:40"), "2026-08-25T17:31:58Z"),
            normalize_item(comment("old", "outside", exact="24 May 2026"), "2026-08-25T17:31:58Z"),
            normalize_item(post("unknown", "unknown date"), "2026-08-25T17:31:58Z"),
        ]
        state = apply_coverage_snapshot(
            state,
            baseline,
            observed_at="2026-08-25T17:31:58Z",
            snapshot_meta={"collectionLimit": {"mode": "date", "cutoffDate": "2024-01-25"}},
            complete=True,
            target_config=CONFIG,
        )
        state = apply_coverage_snapshot(
            state,
            [],
            observed_at="2026-08-25T21:51:38Z",
            snapshot_meta={"collectionLimit": {"mode": "date", "cutoffDate": "2026-06-01"}},
            complete=True,
            target_config=CONFIG,
        )
        self.assertEqual("missing_once", state["entities"]["comment:in"]["status"])
        self.assertEqual("active", state["entities"]["comment:old"]["status"])
        self.assertEqual("active", state["entities"]["post:unknown"]["status"])
        snapshot = state["snapshots"][-1]
        self.assertEqual(1, snapshot["coverageEligiblePriorEntities"])
        self.assertEqual(1, snapshot["coverageUnknownDatePriorEntities"])
        self.assertEqual(1, snapshot["coverageOutsidePriorEntities"])

    def test_partial_snapshot_never_marks_missing_even_with_date_limit(self):
        state = initial_state("school-watchlist")
        baseline = [normalize_item(comment("in", "inside", exact="24 August 2026"), "2026-08-25T17:31:58Z")]
        state = apply_coverage_snapshot(
            state,
            baseline,
            observed_at="2026-08-25T17:31:58Z",
            snapshot_meta={"collectionLimit": {"mode": "date", "cutoffDate": "2024-01-25"}},
            complete=True,
            target_config=CONFIG,
        )
        state = apply_coverage_snapshot(
            state,
            [],
            observed_at="2026-08-25T21:51:38Z",
            snapshot_meta={"collectionLimit": {"mode": "date", "cutoffDate": "2026-06-01"}},
            complete=False,
            target_config=CONFIG,
        )
        self.assertEqual("active", state["entities"]["comment:in"]["status"])


if __name__ == "__main__":
    unittest.main()
