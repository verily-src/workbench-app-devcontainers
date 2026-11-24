"""Tests for the page's Update control, using Streamlit's own test runner.

Run from this folder's parent:
    app/.venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR))

LAUNCHED = {
    "ASK_WORKBENCH_VERSION": "abc1234",
    "ASK_WORKBENCH_REF": "refs/heads/some-branch",
    "ASK_WORKBENCH_EXTRA_ARGS": '["--server.port=9999"]',
}


def run_page(environment: dict) -> AppTest:
    cleared = {name: "" for name in ("ASK_WORKBENCH_REF",)}
    with mock.patch.dict(os.environ, {**cleared, **environment}):
        os.environ.pop("ASK_WORKBENCH_UPDATE_PROBLEM", None)
        if "ASK_WORKBENCH_VERSION" not in environment:
            os.environ.pop("ASK_WORKBENCH_VERSION", None)
        page = AppTest.from_file(str(APP_DIR / "main.py"), default_timeout=30)
        page.run()
        return page


class UpdateControlTests(unittest.TestCase):
    def test_hidden_when_the_app_was_not_started_by_the_launcher(self):
        page = run_page({})
        self.assertFalse(page.exception)
        self.assertEqual([b.key for b in page.button if b.key == "update_app"], [])

    def test_hidden_when_updates_are_off(self):
        page = run_page({"ASK_WORKBENCH_UPDATE_PROBLEM": "updates are off", "ASK_WORKBENCH_REF": ""})
        self.assertEqual([b.key for b in page.button if b.key == "update_app"], [])

    def test_click_reruns_the_launcher_with_the_same_arguments(self):
        with mock.patch.dict(os.environ, LAUNCHED), \
                mock.patch("os.execv") as execv:
            page = AppTest.from_file(str(APP_DIR / "main.py"), default_timeout=30)
            page.run()
            self.assertFalse(page.exception)
            self.assertIn("version abc1234", " ".join(c.value for c in page.caption))
            page.button(key="update_app").click().run()

        execv.assert_called_once()
        program, arguments = execv.call_args.args
        self.assertEqual(program, sys.executable)
        self.assertEqual(arguments, [sys.executable, str(APP_DIR / "launcher.py"), "--server.port=9999"])
        self.assertIn("Updating", " ".join(c.value for c in page.caption))


if __name__ == "__main__":
    unittest.main()
