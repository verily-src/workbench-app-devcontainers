"""Tests for find-model-store.sh: explicit store, bucket-mount search, local fallback."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "src" / "opencode-nemotron-openshell" / "find-model-store.sh"
LIBRARY = Path("manifests") / "registry.ollama.ai" / "library"


def make_store(root: Path, *tags: str) -> Path:
    (root / "blobs").mkdir(parents=True)
    for tag in tags:
        name, _, version = tag.partition(":")
        manifest = root / LIBRARY / name / (version or "latest")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("{}")
    return root


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.workspace = self.home / "workspace"
        self.workspace.mkdir()
        self.local = self.home / ".ollama" / "models"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *tags: str, **env: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, "OPENCODE_HOME": str(self.home), "OLLAMA_MODELS": str(self.local)}
        environment.pop("OPENCODE_MODEL_STORE_SEARCH", None)
        environment.update(env)
        return subprocess.run([str(SCRIPT), *tags], capture_output=True, text=True, env=environment, check=False)

    def test_uses_bucket_store_one_folder_down_that_holds_every_model(self):
        store = make_store(self.workspace / "models" / "ollama-store", "nemotron-3-nano:4b", "nemotron-3.5-lightning:30b")
        result = self.run_script("nemotron-3-nano:4b", "nemotron-3.5-lightning:30b")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(store))
        self.assertIn("instead of downloading", result.stderr)

    def test_uses_store_at_bucket_root(self):
        store = make_store(self.workspace / "ollama-bucket", "nemotron-3-nano:4b")
        self.assertEqual(self.run_script("nemotron-3-nano:4b").stdout.strip(), str(store))

    def test_falls_back_to_local_when_a_model_is_missing(self):
        make_store(self.workspace / "models" / "ollama-store", "nemotron-3-nano:4b")
        result = self.run_script("nemotron-3-nano:4b", "nemotron-3.5-lightning:30b")
        self.assertEqual(result.stdout.strip(), str(self.local))

    def test_ignores_directories_that_are_not_stores(self):
        (self.workspace / "data" / "manifests").mkdir(parents=True)
        self.assertEqual(self.run_script("nemotron-3-nano:4b").stdout.strip(), str(self.local))

    def test_explicit_store_wins_over_search(self):
        make_store(self.workspace / "models" / "ollama-store", "nemotron-3-nano:4b")
        explicit = self.home / "pinned"
        explicit.mkdir()
        (self.home / ".opencode-model-store").write_text(f"{explicit}\n")
        self.assertEqual(self.run_script("nemotron-3-nano:4b").stdout.strip(), str(explicit))

    def test_invalid_explicit_store_fails(self):
        (self.home / ".opencode-model-store").write_text("relative/path\n")
        result = self.run_script("nemotron-3-nano:4b")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an existing absolute directory", result.stderr)

    def test_search_can_be_turned_off(self):
        make_store(self.workspace / "models" / "ollama-store", "nemotron-3-nano:4b")
        result = self.run_script("nemotron-3-nano:4b", OPENCODE_MODEL_STORE_SEARCH="off")
        self.assertEqual(result.stdout.strip(), str(self.local))

    def test_namespaced_tag(self):
        store = self.workspace / "models" / "ollama-store"
        (store / "blobs").mkdir(parents=True)
        manifest = store / "manifests" / "registry.ollama.ai" / "team" / "model" / "v1"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}")
        self.assertEqual(self.run_script("team/model:v1").stdout.strip(), str(store))


if __name__ == "__main__":
    unittest.main()
