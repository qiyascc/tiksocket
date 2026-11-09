from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from tiksocket import parse as dmparse

ZONE = ZoneInfo("UTC")
NOW = datetime(2026, 11, 9, 18, 0, tzinfo=ZONE)
CONV = "0:1:1111111111111111111:2222222222222222222"


class StampTests(unittest.TestCase):
    def test_full_date(self):
        found = dmparse.parse_stamp("October 29, 2026 13:44", NOW)
        self.assertEqual((found.month, found.day, found.hour, found.minute), (10, 29, 13, 44))

    def test_short_date_and_future_is_clamped(self):
        self.assertEqual(dmparse.parse_stamp("10/29/2026", NOW).day, 29)
        self.assertEqual(dmparse.parse_stamp("December 1, 2026 10:00", NOW), NOW)

    def test_relative_words(self):
        self.assertEqual(dmparse.parse_stamp("Yesterday 09:15", NOW).day, 8)
        self.assertEqual(dmparse.parse_stamp("17:20", NOW).day, 9)
        self.assertEqual(dmparse.parse_stamp("19:20", NOW).day, 8)
        monday = dmparse.parse_stamp("Monday 10:00", NOW)
        self.assertEqual(monday.weekday(), 0)
        self.assertLess(monday, NOW)

    def test_garbage(self):
        self.assertIsNone(dmparse.parse_stamp("", NOW))
        self.assertIsNone(dmparse.parse_stamp("soon", NOW))
        self.assertIsNone(dmparse.parse_stamp("February 31, 2026 10:00", NOW))


class ItemTests(unittest.TestCase):
    def test_text_from_peer_and_me(self):
        raw = {"handle": "@jane.doe", "items": [
            {"id": "a", "author": "/@jane.doe", "stamp": "October 29, 2026 13:44", "text": "Hello"},
            {"id": "b", "author": "/@Acme.Shop", "stamp": "October 29, 2026 13:44", "text": "Hello, how can I help"},
        ]}
        data = dmparse.messages(raw, "acme.shop", NOW)
        self.assertEqual(data["handle"], "jane.doe")
        self.assertEqual([(i["id"], i["from_me"], i["kind"]) for i in data["items"]],
                         [("a", False, "text"), ("b", True, "text")])
        self.assertIsInstance(data["items"][0]["at"], int)

    def test_reply_prefix_sticker_video_and_duplicates(self):
        raw = {"items": [
            {"id": "r", "author": "/@x", "text": "Replied to you😂"},
            {"id": "r2", "author": "/@x", "text": "Replied to you\n\nOk"},
            {"id": "s", "author": "/@x", "imgs": ["https://p16-tiktok-dm-sticker-sign-sg.ibyteimg.com/a.awebp"]},
            {"id": "v", "author": "/@me", "video": True, "text": "Creator\n👍", "thumb": "https://p16/t.jpeg"},
            {"id": "v", "author": "/@me", "video": True, "text": "dup"},
            {"id": "", "author": "/@x", "text": "no id"},
            {"id": "e", "author": "/@x", "text": ""},
        ]}
        items = dmparse.messages(raw, "me", NOW)["items"]
        self.assertEqual([i["id"] for i in items], ["r", "r2", "s", "v", "e"])
        self.assertEqual((items[0]["text"], items[0]["reply"]), ("😂", True))
        self.assertEqual(items[1]["text"], "Ok")
        self.assertEqual((items[2]["kind"], items[2]["image"][:8]), ("sticker", "https://"))
        self.assertEqual((items[3]["kind"], items[3]["from_me"], items[3]["thumb"]), ("video_share", True, "https://p16/t.jpeg"))
        self.assertEqual(items[4]["kind"], "unsupported")

    def test_limit_keeps_newest(self):
        raw = {"items": [{"id": str(n), "author": "/@x", "text": str(n)} for n in range(100)]}
        items = dmparse.messages(raw, "me", NOW, limit=5)["items"]
        self.assertEqual([i["id"] for i in items], ["95", "96", "97", "98", "99"])


class OutcomeTests(unittest.TestCase):
    def row(self, id_, text, server="", warning="", author="/@me"):
        return dmparse.classify({"id": id_, "author": author, "text": text, "server": server, "warning": warning}, "me")

    def test_sent_pending_failed_none(self):
        before = {"old"}
        old = self.row("old", "Hello", "more-action-icon-msg-1")
        sent = self.row("new", "Hello  friend", "more-action-icon-msg-7000000000000000001")
        self.assertEqual(dmparse.outcome([old, sent], before, "Hello friend", ""), ("sent", "new"))
        self.assertEqual(sent["server"], "7000000000000000001")
        pending = self.row("new", "Hello friend")
        self.assertEqual(dmparse.outcome([old, pending], before, "Hello friend", ""), ("pending", "new"))
        failed = self.row("new", "Hello friend", warning="<svg></svg>")
        self.assertEqual(dmparse.outcome([old, failed], before, "Hello friend", ""), ("failed", "not_delivered"))
        notice = "You can only send up to 1 message before this user accepts your message request."
        self.assertEqual(dmparse.outcome([old, pending], before, "Hello friend", notice), ("failed", "request_pending"))
        self.assertEqual(dmparse.outcome([old], before, "Hello friend", notice), ("none", ""))

    def test_delivered_drops_our_failed_and_local_bubbles(self):
        rows = [self.row("a", "ok", "more-action-icon-msg-1"), self.row("b", "local"),
                self.row("c", "bad", "more-action-icon-msg-2", warning="<svg/>"), self.row("d", "peer", author="/@peer")]
        self.assertEqual([r["id"] for r in dmparse.delivered(rows)], ["a", "d"])

    def test_peer_message_is_not_ours(self):
        peer = self.row("p", "Hello friend", author="/@peer")
        self.assertEqual(dmparse.outcome([peer], set(), "Hello friend", ""), ("none", ""))


class ChatTests(unittest.TestCase):
    def test_chats_parse_and_skip_bad_ids(self):
        rows = dmparse.chats([
            {"id": CONV, "name": "jane.doe", "rest": "jane.doe\n\nYou shared a video\n\n10/29/2026", "avatar": "https://a"},
            {"id": CONV, "name": "dup", "rest": "dup"},
            {"id": "bad", "name": "x", "rest": "x"},
            {"id": "0:1:1:2", "name": "", "rest": "Alex\nHello\n13:05", "unread": True},
        ])
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0]["preview"], rows[0]["date"], rows[0]["sig"]),
                         ("You shared a video", "10/29/2026", "You shared a video|10/29/2026"))
        self.assertEqual((rows[1]["name"], rows[1]["preview"], rows[1]["date"], rows[1]["unread"]), ("Alex", "Hello", "13:05", True))

    def test_signature_changes_with_new_message(self):
        one = dmparse.chats([{"id": CONV, "name": "a", "rest": "a\nHello\n13:05"}])[0]["sig"]
        two = dmparse.chats([{"id": CONV, "name": "a", "rest": "a\nHow are you\n13:06"}])[0]["sig"]
        self.assertNotEqual(one, two)

    def test_peer_and_blocked(self):
        self.assertEqual(dmparse.peer_of(CONV, "2222222222222222222"), "1111111111111111111")
        self.assertEqual(dmparse.blocked("You're sending messages too fast"), "rate_limited")
        self.assertEqual(dmparse.blocked("Log in to TikTok"), "logged_out")
        self.assertEqual(dmparse.blocked("Messages"), "")


if __name__ == "__main__":
    unittest.main()


def test_post_id_from_publish_response():
    from tiksocket.upload import post_id_from

    assert post_id_from({"status_code": 0, "data": {"item_id": "7706185908088786177"}}) == "7706185908088786177"
    assert post_id_from({"data": [{"x": 1}, {"aweme_id": 7706185224035650822}]}) == "7706185224035650822"
    assert post_id_from({"data": {"item_id": "12"}}) == ""
