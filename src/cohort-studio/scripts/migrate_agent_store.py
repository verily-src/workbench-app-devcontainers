"""Create Aurora storage for assistant sessions and telemetry."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import agent_store_config
from agent_store_migrate import DDL, migrate  # noqa: F401  (DDL kept for importers)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--managed-access", action="store_true",
                        help="Keep existing database permissions; storage is not private.")
    args = parser.parse_args(argv)
    try:
        resource_id = agent_store_config.resource_id()
    except agent_store_config.AgentStoreConfigError as exc:
        raise SystemExit(str(exc)) from exc
    mode = migrate(resource_id, args.managed_access)
    print(f"Agent store schema ready on {resource_id}: {mode}.")


if __name__ == "__main__":
    main()
