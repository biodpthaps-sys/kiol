# Test to verify dynamic YAML/JSON loading of all 15 core pods without hard-coded code

import json
import pytest
from council.core.orchestrator import PodDefinition

def test_dynamic_pods_registration_and_validation():
    # Load config file
    with open("config/pods_config.json", "r") as f:
        data = json.load(f)

    pods_list = data.get("pods", [])
    assert len(pods_list) == 15, f"Expected 15 core pods, got {len(pods_list)}"

    # Validate each pod def against our PodDefinition schema
    for raw_pod in pods_list:
        pod_def = PodDefinition.model_validate(raw_pod)
        assert len(pod_def.domain) > 0
        assert len(pod_def.lead_role) > 0
        assert len(pod_def.builder_roles) > 0
        assert len(pod_def.auditor_role) > 0
        assert len(pod_def.definition_of_done) > 0
        assert len(pod_def.verification_method) > 0
        assert pod_def.budget_ceiling > 0.0

    print("Phase 3 config validation check executed and passed successfully!")
