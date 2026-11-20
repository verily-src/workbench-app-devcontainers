"""start-vllm.sh run against stand-ins for curl, nvidia-smi, df, hf and vllm on PATH."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

FEATURE = Path(__file__).resolve().parents[2] / "features" / "src" / "vllm-model"
MODEL = "nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4"
REVISION = "3acb09951cff50cda7be0200ebbad2c15a3e63ba"


class StartScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.venv = self.root / "venv"
        self.home = self.root / "home"
        for directory in (self.bin, self.venv / "bin", self.home):
            directory.mkdir(parents=True)
        self.hf_calls = self.root / "hf-calls"
        # The script's fixed /opt/vllm is the only thing changed in the copy under test.
        text = (FEATURE / "start-vllm.sh").read_text().replace('readonly VENV="/opt/vllm"', f'readonly VENV="{self.venv}"')
        self.script = self.root / "start-vllm.sh"
        self.script.write_text(text)
        self.stub("curl", "exit 22")
        self.stub("nvidia-smi", "echo 81559; echo 81559")
        self.stub("df", "printf '1M-blocks\\n32768\\n'")
        self.stub(self.venv / "bin" / "hf",
                  f'echo "$@" >> {self.hf_calls}\n'
                  'while [[ $# -gt 0 ]]; do [[ "$1" == --local-dir ]] && dir="$2"; shift; done\n'
                  'mkdir -p "$dir"; echo {} > "$dir/config.json"; : > "$dir/model.safetensors"')
        self.stub(self.venv / "bin" / "vllm", "exit 1")
        self.model_dir = self.home / ".vllm" / "models" / MODEL.replace("/", "--")

    def stub(self, path, body):
        path = path if isinstance(path, Path) else self.bin / path
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)

    def run_script(self):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "APP_USER_HOME": str(self.home)}
        for name in [k for k in env if k.startswith("VLLM_")]:
            del env[name]
        return subprocess.run(["bash", str(self.script)], env=env, capture_output=True, text=True, timeout=60)

    def hf_runs(self):
        return len(self.hf_calls.read_text().splitlines()) if self.hf_calls.exists() else 0

    def test_nothing_listening_reaches_the_gpu_check_instead_of_aborting_on_curl(self):
        self.stub("nvidia-smi", "echo 81559")
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("needs two 80 GB GPUs (2x H100); this VM has 1.", done.stderr)

    def test_a_store_with_config_and_one_shard_but_no_marker_is_downloaded_again(self):
        self.model_dir.mkdir(parents=True)
        (self.model_dir / "config.json").write_text("{}")
        (self.model_dir / "model-00001-of-00009.safetensors").write_text("partial")
        self.run_script()
        self.assertEqual(self.hf_runs(), 1)
        self.assertIn(f"--revision {REVISION}", self.hf_calls.read_text())

    def test_the_marker_is_written_after_a_download_that_succeeds(self):
        self.run_script()
        self.assertEqual((self.model_dir / ".download-complete").read_text().strip(), REVISION)

    def test_no_marker_when_the_download_fails(self):
        self.stub(self.venv / "bin" / "hf", f'echo "$@" >> {self.hf_calls}\nexit 1')
        done = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.hf_runs(), 3)
        self.assertFalse((self.model_dir / ".download-complete").exists())

    def test_a_marker_for_this_revision_skips_the_download_and_another_does_not(self):
        self.model_dir.mkdir(parents=True)
        (self.model_dir / ".download-complete").write_text(REVISION + "\n")
        self.run_script()
        self.assertEqual(self.hf_runs(), 0)
        (self.model_dir / ".download-complete").write_text("0" * 40 + "\n")
        self.run_script()
        self.assertEqual(self.hf_runs(), 1)


if __name__ == "__main__":
    unittest.main()
