import unittest

from scripts.relationships import repair_parent_relationships


POST_PFBID = "pfbid02ztwe8bWU7Ttc2ECsMZ7HBRzZMxgRAniaovt51K6zDfhwxdfFossyeceY78TueGBgl"
NUMERIC_POST_ID = "122137376583037395"
COMMENT_ID = "1762928981418339"


class RelationshipRepairTests(unittest.TestCase):
    def test_exact_comment_source_link_repairs_numeric_parent_to_pfbid_post(self):
        entities = [
            {
                "id": f"post:{POST_PFBID}",
                "itemType": "post",
                "postId": POST_PFBID,
                "author": "School Watchlist",
            },
            {
                "id": f"comment:{COMMENT_ID}",
                "itemType": "comment",
                "commentId": COMMENT_ID,
                "postId": NUMERIC_POST_ID,
                "observedPostId": NUMERIC_POST_ID,
                "parentId": f"post:{NUMERIC_POST_ID}",
                "parentPostPermalink": "https://www.facebook.com/profile.php?id=61581121856469",
                "links": [
                    {
                        "href": (
                            "https://www.facebook.com/permalink.php?"
                            f"story_fbid={POST_PFBID}&id=61581121856469&comment_id={COMMENT_ID}"
                        ),
                        "text": "20h",
                    }
                ],
            },
        ]

        repaired, diagnostics = repair_parent_relationships(entities)
        comment = next(entity for entity in repaired if entity["itemType"] == "comment")

        self.assertEqual(f"post:{POST_PFBID}", comment["parentId"])
        self.assertEqual(POST_PFBID, comment["postId"])
        self.assertEqual(NUMERIC_POST_ID, comment["observedPostId"])
        self.assertEqual("exact_comment_source_link", comment["parentRelationshipMethod"])
        self.assertEqual("high", comment["parentRelationshipConfidence"])
        self.assertEqual(1, diagnostics["linkedComments"])
        self.assertEqual(1, diagnostics["repairedComments"])
        self.assertEqual(0, diagnostics["orphanComments"])

    def test_unrelated_story_link_does_not_reparent_comment(self):
        entities = [
            {
                "id": f"post:{POST_PFBID}",
                "itemType": "post",
                "postId": POST_PFBID,
            },
            {
                "id": "comment:123",
                "itemType": "comment",
                "commentId": "123",
                "postId": "999",
                "parentId": "post:999",
                "links": [
                    {
                        "href": (
                            "https://www.facebook.com/permalink.php?"
                            f"story_fbid={POST_PFBID}&id=61581121856469&comment_id=DIFFERENT"
                        )
                    }
                ],
            },
        ]

        repaired, diagnostics = repair_parent_relationships(entities)
        comment = next(entity for entity in repaired if entity["itemType"] == "comment")

        self.assertEqual("post:999", comment["parentId"])
        self.assertEqual("unresolved", comment["parentRelationshipMethod"])
        self.assertEqual(1, diagnostics["orphanComments"])

    def test_existing_valid_parent_is_preserved(self):
        entities = [
            {
                "id": f"post:{POST_PFBID}",
                "itemType": "post",
                "postId": POST_PFBID,
            },
            {
                "id": "comment:456",
                "itemType": "comment",
                "commentId": "456",
                "postId": POST_PFBID,
                "parentId": f"post:{POST_PFBID}",
                "links": [],
            },
        ]

        repaired, diagnostics = repair_parent_relationships(entities)
        comment = next(entity for entity in repaired if entity["itemType"] == "comment")

        self.assertEqual(f"post:{POST_PFBID}", comment["parentId"])
        self.assertEqual(1, diagnostics["linkedComments"])
        self.assertEqual(0, diagnostics["repairedComments"])


if __name__ == "__main__":
    unittest.main()
