from unittest.mock import patch
from unittest import TestCase
from ergou.group_nicknames import attach


class NicknameTests(TestCase):
    @patch("ergou.group_nicknames.LoginPlugin")
    def test_only_verified_bot_gets_public_nickname(self, plugin):
        rows=[dict(id="a",account=bot,joined=True,detached=False) for bot in ("bot","other")]
        plugin.return_value.request.side_effect=[dict(authenticated=True,ownUsername="bot"),
            dict(groupId="a",username="bot",state="present",member=dict(nickname="寻",roomDisplayName="群名片"))]
        attach(rows)
        self.assertEqual([r["nickname"] for r in rows],["寻",None])

    @patch("ergou.group_nicknames.LoginPlugin",side_effect=ValueError)
    def test_unavailable_plugin_keeps_groups(self, plugin):
        rows=[dict(id="a",account="bot",joined=True,detached=False)]
        attach(rows)
        self.assertIsNone(rows[0]["nickname"])
