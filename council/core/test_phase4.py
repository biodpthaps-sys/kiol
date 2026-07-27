# Test to verify dynamic specialist spawning, task execution, and teardown logic

import pytest
from council.core.schemas import TaskState
from council.core.registries import AgentRegistry
from council.core.workflow import WorkflowEngine
from council.core.governor import ModelRouter, MockLLMAdapter, CostGovernor
from council.core.orchestrator import VerificationHarness
from council.core.specialist import SpecialistSpawner
from council.core.event_bus import EventBus

def test_specialist_lifecycle():
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)
    registry = AgentRegistry()

    cheap_mock = MockLLMAdapter("cheap-mock")
    strong_mock = MockLLMAdapter("strong-mock")
    router = ModelRouter(strong_adapter=strong_mock, cheap_adapter=cheap_mock)
    governor = CostGovernor(global_limit=20.0)
    harness = VerificationHarness(event_bus=bus)

    spawner = SpecialistSpawner(
        agent_registry=registry,
        router=router,
        governor=governor,
        workflow_engine=workflow_engine,
        verification_harness=harness
    )

    # 1. Spawn a specialist agent for narrow domain: Kubernetes configuration
    agent_name = spawner.spawn_specialist(
        domain="Infra/Kubernetes",
        role_name="k8s_specialist",
        mission="Deploy highly scalable multi-replica statefulsets with persistent volumes",
        tools=["kubectl", "helm"],
        budget_ceiling=3.0,
        authority_level=2
    )

    # Verify the agent was successfully registered
    agent_id = registry.get_agent(agent_name)
    assert agent_id is not None
    assert agent_id.role == "k8s_specialist"
    assert agent_id.domain == "Infra/Kubernetes"
    assert agent_id.revocation_status is False

    # 2. Create and execute a task for this specialist
    task = workflow_engine.create_task(
        name="Configure statefulset persistent volume claims",
        description="Write YAML manifests for 3-node PostgreSQL statefulset",
        budget=2.0
    )

    success = spawner.execute_specialist_task(
        agent_name=agent_name,
        task_id=task.task_id,
        auditor_agent_name="k8s_auditor"
    )

    # Verify task successfully completed
    assert success is True
    assert task.state == TaskState.COMPLETED
    assert governor.global_spend > 0.0

    # 3. Teardown specialist
    spawner.teardown_specialist(agent_name)

    # Verify agent was revoked
    agent_revoked = registry.get_agent(agent_name)
    assert agent_revoked.revocation_status is True
    assert agent_name not in spawner.spawned_agents

    # Verify execution of a revoked specialist task fails
    with pytest.raises(RuntimeError):
        spawner.execute_specialist_task(agent_name, task.task_id, "k8s_auditor")

    print("Phase 4 Specialist Spawner lifecycle test executed and passed successfully!")
