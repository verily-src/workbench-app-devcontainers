"""Tests for app/launcher.py. Nothing here touches the network.

Run from this folder's parent:
    app/.venv/bin/python -m unittest discover -s tests -v
"""

import io
import os
import shutil
import sys
import tarfile
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import launcher  # noqa: E402

REPO = "some-owner/some-repo"
REF = "refs/heads/some-branch"
SUBPATH = "src/the-app/app"
COMMIT_A = "a" * 40
COMMIT_B = "b" * 40


def make_archive(path: Path, files: dict, commit: str = "", extra=()) -> None:
    """Write a GitHub-style archive: one top folder, optional commit comment."""
    headers = {"comment": commit} if commit else {}
    with tarfile.open(path, "w:gz", format=tarfile.PAX_FORMAT, pax_headers=headers) as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(f"top/{name}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        for info in extra:
            tar.addfile(info)


def app_files(requirements: bytes = b"streamlit==1.0\n", marker: bytes = b"new") -> dict:
    return {
        f"{SUBPATH}/main.py": b"print('app')",
        f"{SUBPATH}/launcher.py": b"print('launcher')",
        f"{SUBPATH}/requirements.txt": requirements,
        f"{SUBPATH}/version.txt": marker,
        "README.md": b"outside the app folder",
    }


class LauncherTestCase(unittest.TestCase):
    """Gives each test its own live folder and a copy the script 'started from'."""

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="launcher-test-"))
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        self.live = self.work / "live"
        self.archive = self.work / "next.tar.gz"
        self.pip_calls = []
        self.pip_returncode = 0

        patches = [
            mock.patch.object(launcher, "LIVE_ROOT", self.live),
            mock.patch.object(launcher, "download", self.fake_download),
            mock.patch.object(launcher.subprocess, "run", self.fake_pip),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def fake_download(self, url, target):
        self.downloaded_url = url
        shutil.copy(self.archive, target)

    def fake_pip(self, command, **kwargs):
        self.pip_calls.append(command)
        return types.SimpleNamespace(returncode=self.pip_returncode, stderr="pip said no")

    def start_from(self, folder: Path, requirements: str = "streamlit==1.0\n") -> Path:
        """Pretend the script is running from `folder`."""
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "main.py").write_text("print('old app')")
        (folder / "requirements.txt").write_text(requirements)
        patch = mock.patch.object(launcher, "BUILT_IN_DIR", folder)
        patch.start()
        self.addCleanup(patch.stop)
        return folder


class UnpackTests(LauncherTestCase):
    def test_copies_only_plain_files_from_the_app_folder(self):
        link = tarfile.TarInfo(f"top/{SUBPATH}/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        make_archive(self.archive, app_files(), commit=COMMIT_A, extra=[link])
        target = self.work / "out"
        target.mkdir()

        commit = launcher.unpack(self.archive, SUBPATH, target)

        copied = sorted(p.name for p in target.rglob("*"))
        self.assertEqual(copied, ["launcher.py", "main.py", "requirements.txt", "version.txt"])
        self.assertEqual(commit, COMMIT_A)

    def test_refuses_a_path_that_climbs_out(self):
        make_archive(self.archive, {f"{SUBPATH}/../../../evil.txt": b"x"})
        target = self.work / "out"
        target.mkdir()
        with self.assertRaises(launcher.UpdateError):
            launcher.unpack(self.archive, SUBPATH, target)
        self.assertFalse((self.work / "evil.txt").exists())


class LatestAppTests(LauncherTestCase):
    def test_first_start_from_the_image(self):
        self.start_from(self.work / "image")
        make_archive(self.archive, app_files(), commit=COMMIT_A)

        folder, commit = launcher.latest_app(REPO, REF, SUBPATH)

        self.assertEqual((folder, commit), (self.live / COMMIT_A, COMMIT_A))
        self.assertTrue((folder / "main.py").is_file())
        self.assertEqual(self.downloaded_url, f"https://codeload.github.com/{REPO}/tar.gz/{REF}")
        self.assertEqual(self.pip_calls, [], "same package list, so nothing to install")
        self.assertTrue((self.work / "image" / "main.py").is_file(), "the image copy is never touched")

    def test_update_from_a_running_copy_replaces_it(self):
        running = self.start_from(self.live / COMMIT_A)
        make_archive(self.archive, app_files(), commit=COMMIT_B)

        folder, commit = launcher.latest_app(REPO, REF, SUBPATH)

        self.assertEqual(commit, COMMIT_B)
        self.assertEqual((folder / "version.txt").read_text(), "new")
        self.assertFalse(running.exists(), "the old copy is removed once the new one is ready")
        self.assertEqual([p.name for p in self.live.iterdir()], [COMMIT_B])

    def test_update_with_nothing_new_keeps_the_running_copy(self):
        running = self.start_from(self.live / COMMIT_A)
        (running / "kept.txt").write_text("still here")
        make_archive(self.archive, app_files(), commit=COMMIT_A)

        folder, _ = launcher.latest_app(REPO, REF, SUBPATH)

        self.assertEqual(folder, running)
        self.assertTrue((running / "kept.txt").is_file())

    def test_changed_packages_are_installed_once(self):
        self.start_from(self.live / COMMIT_A)
        make_archive(self.archive, app_files(requirements=b"streamlit==1.0\nextra==2.0\n"), commit=COMMIT_B)

        folder, _ = launcher.latest_app(REPO, REF, SUBPATH)

        self.assertEqual(len(self.pip_calls), 1)
        self.assertIn(str(folder / "requirements.txt"), self.pip_calls[0])
        self.assertTrue((folder / ".packages-installed").is_file())

    def test_failed_install_keeps_the_running_copy_to_fall_back_to(self):
        running = self.start_from(self.live / COMMIT_A)
        make_archive(self.archive, app_files(requirements=b"does-not-exist==9.9\n"), commit=COMMIT_B)
        self.pip_returncode = 1

        with self.assertRaises(launcher.UpdateError) as caught:
            launcher.latest_app(REPO, REF, SUBPATH)

        self.assertIn("could not be installed", str(caught.exception))
        self.assertTrue((running / "main.py").is_file(), "the copy in use must survive a failed update")

    def test_download_without_the_app_is_refused(self):
        self.start_from(self.work / "image")
        make_archive(self.archive, {"README.md": b"no app here"}, commit=COMMIT_A)
        with self.assertRaises(launcher.UpdateError) as caught:
            launcher.latest_app(REPO, REF, SUBPATH)
        self.assertIn("did not contain the app", str(caught.exception))

    def test_bad_settings_never_reach_the_network(self):
        self.downloaded_url = None
        for repo, ref in [("bad repo", REF), (REPO, "refs/heads/a b"), (REPO + "/../x", REF), ("", REF)]:
            with self.subTest(repo=repo, ref=ref):
                with self.assertRaises(launcher.UpdateError):
                    launcher.latest_app(repo, ref, SUBPATH)
        self.assertIsNone(self.downloaded_url)


class StartUpTests(unittest.TestCase):
    def test_inherited_files_are_closed_but_standard_streams_are_kept(self):
        with mock.patch.object(launcher.os, "closerange") as closerange:
            launcher.close_inherited_files()
        first, last = closerange.call_args.args
        self.assertEqual(first, 3)
        self.assertGreaterEqual(last, 4096)

    def test_main_closes_inherited_files_before_anything_else(self):
        order = []
        with mock.patch.object(launcher, "close_inherited_files", lambda: order.append("close")), \
                mock.patch.object(launcher, "choose_app", lambda: order.append("choose") or (Path("."), {})), \
                mock.patch.object(launcher.os, "chdir"), \
                mock.patch.object(launcher.os, "execv") as execv, \
                mock.patch.object(launcher.sys, "argv", ["launcher.py", "--server.port=9999"]), \
                mock.patch.dict(os.environ, {}, clear=False):
            launcher.main()
            self.assertEqual(os.environ["ASK_WORKBENCH_EXTRA_ARGS"], '["--server.port=9999"]')
        self.assertEqual(order, ["close", "choose"])
        self.assertEqual(execv.call_args.args[1][-1], "--server.port=9999")


class ChooseAppTests(LauncherTestCase):
    def settings(self, ref=REF):
        return mock.patch.dict(os.environ, {"ASK_WORKBENCH_REPO": REPO, "ASK_WORKBENCH_REF": ref, "ASK_WORKBENCH_PATH": SUBPATH})

    def test_success_reports_the_version(self):
        self.start_from(self.work / "image")
        make_archive(self.archive, app_files(), commit=COMMIT_B)
        with self.settings():
            folder, info = launcher.choose_app()
        self.assertEqual(folder, self.live / COMMIT_B)
        self.assertEqual(info, {"ASK_WORKBENCH_VERSION": "b" * 7})

    def test_failure_falls_back_and_says_why(self):
        started_from = self.start_from(self.work / "image")
        make_archive(self.archive, {"README.md": b"no app here"})
        with self.settings():
            folder, info = launcher.choose_app()
        self.assertEqual(folder, started_from)
        self.assertEqual(info, {"ASK_WORKBENCH_UPDATE_PROBLEM": "the download did not contain the app"})

    def test_failed_update_of_a_running_copy_keeps_its_version(self):
        running = self.start_from(self.live / COMMIT_A)
        make_archive(self.archive, {"README.md": b"no app here"})
        with self.settings():
            folder, info = launcher.choose_app()
        self.assertEqual(folder, running)
        self.assertEqual(info, {
            "ASK_WORKBENCH_UPDATE_PROBLEM": "the download did not contain the app",
            "ASK_WORKBENCH_VERSION": "a" * 7,
        })

    def test_empty_ref_turns_updates_off(self):
        started_from = self.start_from(self.work / "image")
        with self.settings(ref=""):
            folder, info = launcher.choose_app()
        self.assertEqual(folder, started_from)
        self.assertEqual(info, {"ASK_WORKBENCH_UPDATE_PROBLEM": "updates are off"})


if __name__ == "__main__":
    unittest.main()
