import unittest

from scouts.instagram_harvest import item_to_reel, render_template, split_keywords, to_int


class HarvestMappingTests(unittest.TestCase):
    def test_common_field_names(self):
        r = item_to_reel({"shortCode": "abc", "url": "https://x/abc", "ownerUsername": "jo", "ownerFollowersCount": 1200,
                          "caption": "hi", "videoPlayCount": 5000, "likesCount": 100, "commentsCount": 7,
                          "timestamp": "2026-10-10T08:00:00.000Z"})
        self.assertEqual((r.id, r.account, r.followers, r.plays, r.likes, r.comments), ("abc", "jo", 1200, 5000, 100, 7))
        self.assertIsNotNone(r.posted_at)

    def test_alternative_names_and_nested_owner(self):
        r = item_to_reel({"id": 99, "owner": {"username": "mo", "followersCount": 50}, "viewCount": 42,
                          "likeCount": 3, "commentCount": 1, "taken_at": 1760000000})
        self.assertEqual((r.id, r.account, r.followers, r.plays), ("99", "mo", 50, 42))
        self.assertTrue(r.url.endswith("/99/"))

    def test_hidden_likes_become_zero(self):
        self.assertEqual(to_int(-1), 0)
        self.assertEqual(to_int(None), 0)
        self.assertEqual(to_int("12.0"), 12)

    def test_item_without_id_or_url_is_skipped(self):
        self.assertIsNone(item_to_reel({"caption": "orphan"}))

    def test_custom_field_map_overrides(self):
        r = item_to_reel({"weird_views": 777, "id": "z"}, field_map={"plays": ["weird_views"]})
        self.assertEqual(r.plays, 777)

    def test_missing_followers_stays_none(self):
        self.assertIsNone(item_to_reel({"id": "z"}).followers)

    def test_keyword_split_and_template(self):
        hashtags, terms = split_keywords(["#a", "b c", "#d"])
        self.assertEqual((hashtags, terms), (["a", "d"], ["b c"]))
        out = render_template({"h": "{hashtags}", "n": 3, "l": ["{terms}", "x"]},
                              {"{hashtags}": hashtags, "{terms}": terms})
        self.assertEqual(out, {"h": ["a", "d"], "n": 3, "l": ["b c", "x"]})


if __name__ == "__main__":
    unittest.main()


class LiveGlueTests(unittest.TestCase):
    """Exercise harvest() and AnthropicLLM with stand-in modules. Checks our glue code only;
    the real Apify and Anthropic services are not contacted."""

    KEYWORD_ITEMS = [{"id": "a", "url": "u1", "videoPlayCount": 10}, {"caption": "no id"},
                     {"id": "b", "url": "u2", "videoPlayCount": 20}, {"id": "c", "url": "u3"}]
    PROFILE_ITEMS = [{"id": "p1", "url": "pu1", "ownerUsername": "jo"}, {"id": "p2", "url": "pu2", "ownerUsername": "jo"}]

    def setUp(self):
        import sys, types
        self.sys, self.calls = sys, {"runs": []}
        calls, kw_items, pr_items = self.calls, self.KEYWORD_ITEMS, self.PROFILE_ITEMS

        class FakeDataset:
            def __init__(self_inner, ds_id):
                self_inner.ds_id = ds_id
            def iterate_items(self_inner):
                yield from (pr_items if self_inner.ds_id == "ds:profile/actor" else kw_items)

        class FakeActor:
            def __init__(self_inner, actor_id):
                self_inner.actor_id = actor_id
            def call(self_inner, run_input):
                calls["runs"].append((self_inner.actor_id, run_input))
                return {"defaultDatasetId": f"ds:{self_inner.actor_id}"}

        class FakeClient:
            def __init__(self_inner, token):
                calls["token"] = token
            def actor(self_inner, actor_id):
                return FakeActor(actor_id)
            def dataset(self_inner, ds_id):
                return FakeDataset(ds_id)

        mod = types.ModuleType("apify_client")
        mod.ApifyClient = FakeClient
        self._saved = sys.modules.get("apify_client")
        sys.modules["apify_client"] = mod

    def tearDown(self):
        if self._saved is None:
            self.sys.modules.pop("apify_client", None)
        else:
            self.sys.modules["apify_client"] = self._saved

    CFG = {"actor_id": "me/actor", "input_template": {"hashtags": "{hashtags}", "searchTerms": "{terms}", "resultsLimit": 30},
           "profile_actor_id": "profile/actor", "profile_input_template": {"usernames": "{usernames}", "resultsLimit": 12}}

    def test_keywords_only(self):
        from scouts.instagram_harvest import harvest
        reels, info = harvest(["#tag", "a term"], self.CFG, "TOKEN")
        self.assertEqual(self.calls["runs"], [("me/actor", {"hashtags": ["tag"], "searchTerms": ["a term"], "resultsLimit": 30})])
        self.assertEqual(self.calls["token"], "TOKEN")
        self.assertEqual([r.id for r in reels], ["a", "b", "c"])
        self.assertEqual((info["items"], info["skipped"], info["creator_accounts"]), (4, 1, 0))
        self.assertEqual(len(info["raw_sample"]), 3)
        capped, _ = harvest(["x"], self.CFG, "T", max_reels=2)
        self.assertEqual(len(capped), 2)

    def test_creators_come_first_and_count_against_the_cap(self):
        from scouts.instagram_harvest import harvest
        reels, info = harvest(["#tag"], self.CFG, "T", max_reels=4, creators=["@jo", "mo"])
        self.assertEqual([a for a, _ in self.calls["runs"]], ["profile/actor", "me/actor"])
        self.assertEqual(self.calls["runs"][0][1], {"usernames": ["jo", "mo"], "resultsLimit": 12})   # "@" stripped
        self.assertEqual([r.id for r in reels], ["p1", "p2", "a", "b"])
        self.assertEqual([r.source for r in reels], ["creator", "creator", "keyword", "keyword"])
        self.assertEqual(info["creator_accounts"], 2)

    def test_creators_can_use_up_the_whole_cap(self):
        from scouts.instagram_harvest import harvest
        reels, info = harvest(["#tag"], self.CFG, "T", max_reels=2, creators=["jo"])
        self.assertEqual([r.id for r in reels], ["p1", "p2"])
        self.assertEqual(len(self.calls["runs"]), 1)          # keyword actor never called
        self.assertNotIn("keywords", info)

    def test_creators_without_a_profile_actor_fail_loudly(self):
        from scouts.instagram_harvest import harvest
        cfg = {**self.CFG, "profile_actor_id": "REPLACE_ME"}
        with self.assertRaises(RuntimeError):
            harvest(["x"], cfg, "T", creators=["jo"])
        self.assertEqual(self.calls["runs"], [])               # nothing was spent

    def test_harvest_refuses_unconfigured_actor(self):
        from scouts.instagram_harvest import harvest
        with self.assertRaises(RuntimeError):
            harvest(["x"], {"actor_id": "REPLACE_ME"}, "T")

    def test_anthropic_wrapper_request_and_parse(self):
        import types
        seen = {}

        class Block:
            type, text = "text", '```json\n{"ok": true}\n```'

        class Messages:
            def create(self_inner, **kw):
                seen.update(kw)
                return types.SimpleNamespace(content=[Block()])

        class Client:
            messages = Messages()

        mod = types.ModuleType("anthropic")
        mod.Anthropic = Client
        saved = self.sys.modules.get("anthropic")
        self.sys.modules["anthropic"] = mod
        try:
            from scouts.llm import AnthropicLLM
            out = AnthropicLLM(model="test-model").complete_json("SYS", "USER")
        finally:
            if saved is None:
                self.sys.modules.pop("anthropic", None)
            else:
                self.sys.modules["anthropic"] = saved
        self.assertEqual(out, {"ok": True})
        self.assertEqual(seen["model"], "test-model")
        self.assertTrue(seen["system"].startswith("SYS"))
        self.assertEqual(seen["messages"], [{"role": "user", "content": "USER"}])


if __name__ == "__main__":
    unittest.main()
