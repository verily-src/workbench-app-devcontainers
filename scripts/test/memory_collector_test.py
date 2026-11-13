import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "tests/common/memory-collect.sh"


class CollectorInterfaceTest(unittest.TestCase):
    def run_interface(self, missed_child=False, host_oom_before=0, host_oom_during=0):
        with tempfile.TemporaryDirectory(prefix="memory-collector-") as tmp:
            directory = Path(tmp)
            cgroup = directory / "cgroup"
            proc = directory / "proc"
            tools = directory / "bin"
            tools.mkdir()
            (proc / "4242").mkdir(parents=True)
            (proc / "sys/kernel/random").mkdir(parents=True)
            (proc / "sys/kernel/random/boot_id").write_text("cold-boot-fixture\n")
            (proc / "meminfo").write_text("MemTotal: 8388608 kB\nMemAvailable: 7340032 kB\n")
            (proc / "4242/cgroup").write_text("0::/app\n")
            cgroup.mkdir()
            (cgroup / "cgroup.controllers").write_text("memory\n")
            for name in ("app", "system.slice"):
                group = cgroup / name
                group.mkdir()
                for field, value in {"peak": "1048576", "current": "1024", "max": "1073741824",
                                     "swap.peak": "0", "events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0"}.items():
                    (group / ("memory." + field)).write_text(value + "\n")
            host_events = cgroup / "system.slice/memory.events"
            host_events.write_text(f"oom {host_oom_before}\noom_kill {host_oom_before}\n")
            metadata = [{"Id": "a" * 64, "Name": "/application-server", "Config": {"Labels": {}},
                         "State": {"Running": True, "Pid": 4242, "StartedAt": "2026-10-08T18:00:00Z", "FinishedAt": "", "OOMKilled": False}}]
            metadata_path = directory / "docker.json"
            metadata_path.write_text(json.dumps(metadata))
            events_path = directory / "events.jsonl"
            events_path.write_text(json.dumps({"Actor": {"ID": "b" * 64, "Attributes": {"name": "dependency-short-child"}}}) + "\n" if missed_child else "")
            scripts = {
                "docker": f'#!/bin/bash\ncase "$1" in ps) echo {"a" * 64} ;; inspect) cat "{metadata_path}" ;; events) cat "{events_path}" ;; *) exit 1 ;; esac\n',
                "timeout": '#!/bin/bash\nshift\nexec "$@"\n',
                "date": '#!/usr/bin/env python3\nimport subprocess,sys,time\nif sys.argv[1:]==["+%s%3N"]: print(int(time.time()*1000))\nelse: sys.exit(subprocess.call(["/bin/date",*sys.argv[1:]]))\n',
            }
            for name, text in scripts.items():
                path = tools / name
                path.write_text(text)
                path.chmod(0o755)
            context = {"schema_version": 1, "run_id": "fixture", "app": "example", "cloud": "gcp", "profile": "cpu",
                       "sample": 1, "inputs_hash": "fixture", "source_sha": "a" * 40,
                       "machine": {"type": "fixture", "ram_bytes": 0, "gpu_type": "", "gpu_count": 0}}
            context_path = directory / "context.json"
            context_path.write_text(json.dumps(context))
            workload = directory / "workload.json"
            workload.write_text(json.dumps({"status": "pass", "execution_mode": "cloud", "workload_sha256": "fixture", "expected_containers": ["application-server"]}))
            output = directory / "report"
            env = dict(os.environ, MEMORY_CGROUP_ROOT=str(cgroup), MEMORY_PROC_ROOT=str(proc), PATH=str(tools) + os.pathsep + os.environ["PATH"])
            start = subprocess.run(["bash", str(COLLECTOR), "start", str(context_path), str(output)], env=env, capture_output=True, text=True)
            log = (output / "collector.log").read_text() if (output / "collector.log").exists() else ""
            self.assertEqual(start.returncode, 0, start.stderr + log)
            try:
                host_events.write_text(f"oom {host_oom_before + host_oom_during}\noom_kill {host_oom_before + host_oom_during}\n")
                (cgroup / "app/memory.peak").write_text("134217728\n")
                result = subprocess.run(["bash", str(COLLECTOR), "finish", str(output), str(workload)], env=env, capture_output=True, text=True, timeout=20)
                failed = missed_child or host_oom_during > 0
                self.assertEqual(result.returncode, int(failed), result.stderr + (output / "collector.log").read_text())
                report = json.loads((output / "memory.json").read_text())
                self.assertEqual(report["status"], "fail" if failed else "pass")
                self.assertEqual(report["provenance"]["cold_boot_id"], "cold-boot-fixture")
                self.assertTrue(any(group["peak_bytes"] == 134217728 for group in report["cgroups"]))
                self.assertGreater(report["host"]["samples"], 0)
                host_group = next(group for group in report["cgroups"] if group["path"] == "/system.slice")
                self.assertEqual(host_group["oom_start"], host_oom_before)
                self.assertEqual(host_group["oom_delta"], host_oom_during)
                self.assertEqual(host_group["oom_kill_delta"], host_oom_during)
                if missed_child:
                    self.assertTrue(any("missed between samples" in reason for reason in report["coverage"]["missing_metrics"]))
            finally:
                (output / "stop").touch()
                deadline = time.monotonic() + 5
                while not (output / "collector.exit").exists() and time.monotonic() < deadline:
                    time.sleep(0.1)

    def test_two_phase_interface_keeps_peak_after_short_spike(self):
        self.run_interface()

    def test_preexisting_host_oom_does_not_fail_a_later_collection(self):
        self.run_interface(host_oom_before=2)

    def test_host_oom_after_start_fails_even_with_preexisting_events(self):
        self.run_interface(host_oom_before=2, host_oom_during=1)

    def test_event_for_unobserved_short_child_blocks_the_sample(self):
        self.run_interface(missed_child=True)


if __name__ == "__main__":
    unittest.main()
