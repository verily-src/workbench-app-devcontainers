"""Tests for find-model-store.sh: explicit store, bucket-mount search, local fallback."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "src" / "vllm-model" / "find-model-store.sh"
LIGHTNING = "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"


def make_store(root: Path, *model_ids: str) -> Path:
    """A store in the layout `hf download --local-dir` writes: one folder per model."""
    for model_id in model_ids:
        folder = root / model_id.replace("/", "--")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text("{}")
        (folder / "model-00001-of-00002.safetensors").write_bytes(b"")
    return root


class ModelStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.workspace = self.home / "workspace"
        self.workspace.mkdir()
        self.local = self.home / ".vllm" / "models"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *model_ids: str, **env: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, "APP_USER_HOME": str(self.home), "VLLM_MODELS": str(self.local)}
        environment.pop("VLLM_MODEL_STORE_SEARCH", None)
        environment.update(env)
        return subprocess.run([str(SCRIPT), *model_ids], capture_output=True, text=True, env=environment, check=False)

    def test_uses_bucket_store_one_folder_down_that_holds_every_model(self):
        store = make_store(self.workspace / "models" / "vllm-store", NANO, LIGHTNING)
        result = self.run_script(NANO, LIGHTNING)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(store))
        self.assertIn("instead of downloading", result.stderr)

    def test_uses_store_at_bucket_root(self):
        store = make_store(self.workspace / "vllm-bucket", NANO)
        self.assertEqual(self.run_script(NANO).stdout.strip(), str(store))

    def test_falls_back_to_local_when_a_model_is_missing(self):
        make_store(self.workspace / "models" / "vllm-store", NANO)
        result = self.run_script(NANO, LIGHTNING)
        self.assertEqual(result.stdout.strip(), str(self.local))

    def test_ignores_directories_that_are_not_stores(self):
        # A folder with the right name but no weights is not a store.
        (self.workspace / "data" / NANO.replace("/", "--")).mkdir(parents=True)
        self.assertEqual(self.run_script(NANO).stdout.strip(), str(self.local))

    def test_requires_safetensors_not_only_config(self):
        folder = self.workspace / "models" / NANO.replace("/", "--")
        folder.mkdir(parents=True)
        (folder / "config.json").write_text("{}")
        self.assertEqual(self.run_script(NANO).stdout.strip(), str(self.local))

    def test_explicit_store_wins_over_search(self):
        make_store(self.workspace / "models" / "vllm-store", NANO)
        explicit = self.home / "pinned"
        explicit.mkdir()
        (self.home / ".vllm-model-store").write_text(f"{explicit}\n")
        self.assertEqual(self.run_script(NANO).stdout.strip(), str(explicit))

    def test_invalid_explicit_store_fails(self):
        (self.home / ".vllm-model-store").write_text("relative/path\n")
        result = self.run_script(NANO)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not an existing absolute directory", result.stderr)

    def test_search_can_be_turned_off(self):
        make_store(self.workspace / "models" / "vllm-store", NANO)
        result = self.run_script(NANO, VLLM_MODEL_STORE_SEARCH="off")
        self.assertEqual(result.stdout.strip(), str(self.local))

    def test_custom_model_id(self):
        store = make_store(self.workspace / "models" / "vllm-store", "team/model-v1")
        self.assertEqual(self.run_script("team/model-v1").stdout.strip(), str(store))


if __name__ == "__main__":
    unittest.main()
