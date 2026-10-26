"""Remove expired assistant run telemetry while retaining conversation history."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from agent_store import AgentStore
from agent_plan_store import AgentPlanStore
import agent_store_config


def main() -> None:
    try:
        resource_id = agent_store_config.resource_id()
    except agent_store_config.AgentStoreConfigError as exc:
        raise SystemExit(str(exc)) from exc
    removed_runs = AgentStore(resource_id).cleanup()
    removed_plans = AgentPlanStore(resource_id).cleanup()
    print(f"Removed {removed_runs} expired agent telemetry runs and {removed_plans} workflow plans.")


if __name__ == "__main__":
    main()
