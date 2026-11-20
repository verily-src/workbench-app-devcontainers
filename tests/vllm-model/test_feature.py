"""The vllm-model feature: the release it pins, the recipe's flags, and the app's wiring."""
import json
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FEATURE = REPO / "features" / "src" / "vllm-model"
APP = REPO / "src" / "ai-research-assistant"
MODEL = "nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-NVFP4"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.release = json.loads((FEATURE / "vllm-release.json").read_text())
        self.install = (FEATURE / "install.sh").read_text()

    def test_a_released_vllm_with_the_flashinfer_it_pins(self):
        self.assertEqual((self.release["version"], self.release["flashinfer_version"]), ("0.34.0", "0.7.3"))
        self.assertIn('"vllm==${release_version}"', self.install)
        for stale in ("wheels.vllm.ai", "uv sync", "pyproject.toml", "uv.lock", "--pre"):
            self.assertNotIn(stale, self.install, stale)
        self.assertFalse(any(FEATURE.glob("*.lock")))

    def test_flashinfer_is_prebuilt_for_h100(self):
        self.assertIn("flashinfer_cubin-${flashinfer_version}-py3-none-any.whl", self.install)
        self.assertIn('"flashinfer-jit-cache-sm90a==${flashinfer_version}+cu130"', self.install)
        self.assertRegex(self.install, r'--no-deps [^\n]*\\\n +"flashinfer-jit-cache==\$\{flashinfer_version\}\+cu130"',
                         "the shim alone: its dependencies are every architecture's kernels")
        self.assertLess(self.install.index("pip\" check"), self.install.index('"flashinfer-jit-cache==${'))

    def test_the_installer_brings_the_cuda_toolkit_the_first_start_compiles_with(self):
        self.assertIn("cuda-toolkit-13-0", self.install)
        self.assertIn('readonly CUDA_DIR="/usr/local/cuda-13.0"', (FEATURE / "start-vllm.sh").read_text())

    def test_the_vertex_endpoint_runs_the_same_release_and_weights(self):
        deploy = (REPO / "features" / "src" / "vertex-model" / "deploy-endpoint.sh").read_text()
        start = (FEATURE / "start-vllm.sh").read_text()
        self.assertIn(f'readonly VLLM_TAG="v{self.release["version"]}"', deploy)
        revision = re.search(r'readonly REVISION="([0-9a-f]{40})"', deploy).group(1)
        self.assertIn(f'REVISION="{revision}"', start)


class RecipeTests(unittest.TestCase):
    def test_the_server_starts_with_the_recipes_flags(self):
        start = (FEATURE / "start-vllm.sh").read_text()
        for flag in ("--tensor-parallel-size 2", "--language-model-only", "--trust-remote-code",
                     "--mamba-backend flashinfer", "--mamba-cache-mode align", "--mamba-ssm-cache-dtype float16",
                     "--enable-mamba-cache-stochastic-rounding", "--mamba-cache-philox-rounds 5",
                     "--enable-mamba-shared-prefix-checkpoint", "--block-size 64", "--prefix-match-unit 64",
                     "--max-num-batched-tokens 16384", "--reasoning-parser nemotron_v3",
                     "--tool-call-parser qwen3_coder", "--tool-strict-level parameter", "--enable-auto-tool-choice"):
            self.assertIn(flag, start, flag)
        self.assertIn('VLLM_FLASHINFER_ALLREDUCE_BACKEND="${VLLM_FLASHINFER_ALLREDUCE_BACKEND:-trtllm}"', start)
        self.assertIn('"backend": "xgrammar", "disable_any_whitespace": true', start)
        self.assertIn('Enough thinking, time to act.', start)
        self.assertNotIn("--speculative-config", start, "it degraded tool calls")
        self.assertNotIn("VLLM_USE_V2_MODEL_RUNNER", start, "the only model runner since 0.34.0")
        self.assertIn('--served-model-name "${MODEL}" \\', start, "one name: the one the app uses")
        self.assertIn(MODEL, start)
        self.assertIn("'$1 + 0 >= 79000'", start, "the same GPU need as ai-policy's access.py")


class AppTests(unittest.TestCase):
    def test_the_app_serves_super_vl_with_room_in_shared_memory_and_context(self):
        compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        app = compose["services"]["app"]
        self.assertEqual(app["shm_size"], "32g")
        env = app["environment"]
        self.assertEqual((env["VLLM_MODEL"], env["VLLM_CONTEXT_LENGTH"]), (MODEL, "262144"))
        self.assertNotIn("VLLM_RECIPE", env)
        self.assertEqual(compose["services"]["sandbox-broker"]["environment"]["AGENT_CONTEXT_LENGTH"], env["VLLM_CONTEXT_LENGTH"])
        features = json.loads((APP / ".devcontainer.json").read_text())["features"]
        self.assertEqual(features["./.devcontainer/features/vllm-model"], {"username": "abc", "userHomeDir": "/config"})
        self.assertEqual([name for name in features if "vllm" in name], ["./.devcontainer/features/vllm-model"])

    def test_start_services_starts_the_one_server(self):
        start = (APP / "start-services.sh").read_text()
        self.assertIn("/opt/vllm-model/start-vllm.sh", start)
        self.assertNotIn("VLLM_RECIPE", start)
        self.assertNotIn("--recipe", start)


if __name__ == "__main__":
    unittest.main()
