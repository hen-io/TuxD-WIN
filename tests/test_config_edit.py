import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.modules.setdefault("psutil", mock.MagicMock())
sys.path.insert(0, ".")
from modules import config_agent

GOOD = "device:\n  name: BOX\nhome-assistant:\n  url: https://ha\n"


class Agent(config_agent.ConfigAgentMixin):
    def __init__(self):
        self.sent = []

    def _send_wait(self, message, timeout):
        self.sent.append(message)


class ConfigEditTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.dir.name)
        open("tuxd-win.conf", "w").write(GOOD)
        self.agent = Agent()

    def tearDown(self):
        os.chdir(self.cwd)
        self.dir.cleanup()

    def ask(self, action, content=None):
        self.agent.handle_config_request(json.dumps({"request_id": "1", "action": action, "content": content}))
        return self.agent.sent[-1]

    def test_get_returns_the_file(self):
        r = self.ask("get")
        self.assertTrue(r["ok"])
        self.assertEqual(r["content"], GOOD)

    def test_set_saves_and_keeps_a_backup(self):
        new = GOOD + "metrics:\n  enabled: false\n"
        self.assertTrue(self.ask("set", new)["ok"])
        self.assertEqual(open("tuxd-win.conf").read(), new)
        self.assertEqual(open("tuxd-win.conf.bak").read(), GOOD)

    def test_refuses_what_the_agent_cannot_start_from(self):
        for bad in ("just text", "device:\n  name: ''\nhome-assistant:\n  url: x\n", "device:\n  name: A\n", "a: [unclosed"):
            r = self.ask("set", bad)
            self.assertFalse(r["ok"], bad)
        self.assertEqual(open("tuxd-win.conf").read(), GOOD)


if __name__ == "__main__":
    unittest.main()
