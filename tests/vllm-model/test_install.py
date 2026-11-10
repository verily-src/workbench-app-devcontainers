"""install.sh of the vllm-model feature: every file it copies or globs exists in the feature."""
import re
import unittest
from pathlib import Path

FEATURE = Path(__file__).resolve().parents[2] / "features" / "src" / "vllm-model"


class InstallTests(unittest.TestCase):
    def test_every_copied_file_ships_with_the_feature(self):
        text = (FEATURE / "install.sh").read_text()
        copied = re.findall(r'"\$\{FEATURE_DIR\}"/([A-Za-z0-9_.-]+)', text)
        self.assertGreater(len(copied), 5)
        for name in copied:
            self.assertTrue((FEATURE / name).exists(), f"install.sh copies {name}, which the feature does not ship")

    def test_every_glob_it_chmods_matches_something_it_installed(self):
        text = (FEATURE / "install.sh").read_text()
        copied = set(re.findall(r'"\$\{FEATURE_DIR\}"/([A-Za-z0-9_.-]+)', text))
        for pattern in re.findall(r'"\$\{INSTALL_DIR\}"/(\*\.[a-z]+)', text):
            suffix = pattern[1:]
            self.assertTrue(any(name.endswith(suffix) for name in copied),
                            f"install.sh chmods {pattern} but installs no such file; the glob would fail the build")


if __name__ == "__main__":
    unittest.main()
