import json
from datetime import datetime
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_ROOT = WORKSPACE_ROOT / "orchestration" / "n8n" / "deployment"
TOPOLOGY_PATH = DEPLOYMENT_ROOT / "topology.json"


def load_topology() -> dict:
    return json.loads(TOPOLOGY_PATH.read_text(encoding="utf-8-sig"))


def test_topology_records_required_environment_boundaries() -> None:
    topology = load_topology()

    required_sections = {
        "n8n",
        "runner",
        "runtime_storage",
        "lock_store",
        "credential_store",
        "network_boundary",
        "inspected_at",
    }
    assert required_sections <= topology.keys()
    assert all(isinstance(topology[name], dict) for name in required_sections - {"inspected_at"})
    datetime.fromisoformat(topology["inspected_at"].replace("Z", "+00:00"))


def test_topology_is_reproducible_and_contains_no_secret_values() -> None:
    topology = load_topology()

    assert topology["runner"]["workspace"] == str(WORKSPACE_ROOT)
    assert topology["runtime_storage"]["runtime_root"] == str(
        WORKSPACE_ROOT / "runtime"
    )
    assert topology["runtime_storage"]["deliveries_root"] == str(
        WORKSPACE_ROOT / "deliveries"
    )
    assert topology["credential_store"]["values_inspected"] is False

    serialized = json.dumps(topology, ensure_ascii=False).lower()
    for forbidden in ("password", "passwd", "token", "cookie", "authorization"):
        assert forbidden not in serialized


def test_unverified_lock_store_is_not_reported_as_available() -> None:
    topology = load_topology()
    lock_store = topology["lock_store"]

    if not (
        lock_store["atomic_compare_and_set_verified"]
        and lock_store["lease_renewal_verified"]
    ):
        assert lock_store["status"] == "unavailable"
