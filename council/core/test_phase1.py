# Comprehensive suite verifying Phase 1 end-to-end Orchestrator/Pod execution loops

import json
import pytest
from council.core.schemas import TaskState, AgentOutputContract
from council.core.registries import AgentRegistry, AgentIdentity, RoleConfig
from council.core.workflow import WorkflowEngine
from council.core.governor import ModelRouter, MockLLMAdapter, CostGovernor
from council.core.orchestrator import GoalBrief, PodDefinition, VerificationHarness, PodRunner, Orchestrator
from council.core.event_bus import EventBus

def test_phase_1_end_to_end():
    # 1. Initialize Event Bus and Engine components
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)

    # Track bus event count
    events_received = []
    bus.subscribe("*", lambda e: events_received.append(e))

    # 2. Register mock adapters representing tiered-compute router
    cheap_mock = MockLLMAdapter("cheap-mock-model")
    strong_mock = MockLLMAdapter("strong-mock-model")
    router = ModelRouter(strong_adapter=strong_mock, cheap_adapter=cheap_mock)

    # 3. Setup Cost Governor
    governor = CostGovernor(global_limit=10.0)

    # 4. Initialize agent registries and role registry
    registry = AgentRegistry()

    # Register Role configs
    registry.register_role(RoleConfig(
        name="backend_lead", domain="Backend Engineering", responsibilities=["Architecture", "Decomposition"], allowed_tools=["*"]
    ))
    registry.register_role(RoleConfig(
        name="backend_builder", domain="Backend Engineering", responsibilities=["Code development"], allowed_tools=["*"]
    ))
    registry.register_role(RoleConfig(
        name="backend_auditor", domain="Backend Engineering", responsibilities=["Independent review"], allowed_tools=["*"]
    ))

    # Register actual Agent identities with authority levels
    registry.register_agent(AgentIdentity(
        name="BackendLeadAgent", role="backend_lead", domain="Backend Engineering", authority_level=4, mission="Lead the backend pod", owner="CTO"
    ))
    registry.register_agent(AgentIdentity(
        name="BackendBuilderAgent", role="backend_builder", domain="Backend Engineering", authority_level=2, mission="Build backend components", owner="backend_lead"
    ))
    registry.register_agent(AgentIdentity(
        name="BackendAuditorAgent", role="backend_auditor", domain="Backend Engineering", authority_level=3, mission="Perform independent audits", owner="backend_lead"
    ))

    # 5. Build Verification Harness
    harness = VerificationHarness(event_bus=bus)

    # 6. Define and register the Backend Engineering Pod
    backend_pod_def = PodDefinition(
        domain="Backend Engineering",
        lead_role="backend_lead",
        builder_roles=["backend_builder"],
        auditor_role="backend_auditor",
        definition_of_done=["Code is syntactically complete", "Verified robustly", "No placeholders"],
        verification_method="automations + auditor review",
        budget_ceiling=5.0
    )

    pod_runner = PodRunner(
        pod_def=backend_pod_def,
        agent_registry=registry,
        router=router,
        governor=governor,
        workflow_engine=workflow_engine,
        verification_harness=harness
    )

    orchestrator = Orchestrator(
        agent_registry=registry,
        router=router,
        governor=governor,
        workflow_engine=workflow_engine,
        verification_harness=harness
    )
    orchestrator.register_pod(pod_runner)

    # 7. Goal Brief Submission (Goal Intake)
    brief = GoalBrief(
        goal="Construct an asynchronous SQLite-backed durable event store for multi-agent coordination metrics",
        success_criteria=["No data drift", "Compaction cron job logs successfully", "Subtask execution completes"],
        budget_ceiling=5.0
    )

    # Execute complete Orchestration loop
    result = orchestrator.handle_goal(brief)

    # Verify execution output and state transitions
    assert result["status"] == "completed"
    main_task = workflow_engine.get_task(result["main_task_id"])
    subtask = workflow_engine.get_task(result["subtask_id"])

    assert main_task.state == TaskState.COMPLETED
    assert subtask.state == TaskState.COMPLETED

    # Check that Cost Governor tracked the transaction costs and LLM generation costs correctly
    assert governor.global_spend > 0.0
    assert "Backend Engineering" in governor.pod_spend
    assert result["subtask_id"] in governor.task_spend

    # Ensure that event notifications were published on the system bus
    assert len(events_received) > 0
    # Let's verify we have at least state change events
    state_changed_topics = [e.topic for e in events_received if "state_changed" in e.topic]
    assert len(state_changed_topics) > 0

    print("Phase 1 integration test runs successfully!")


def test_phase_1_auditor_rejection_and_escalation():
    """Verify that if the auditor rejects the output continuously, it gets escalated after 3 retries."""
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)

    cheap_mock = MockLLMAdapter("cheap-mock-model")
    strong_mock = MockLLMAdapter("strong-mock-model")

    # Inject persistent auditor rejection payload inside strong model
    rejection_payload = AgentOutputContract(
        task_id="test",
        role="backend_auditor",
        objective="audit",
        result="[REJECT] The builder omitted key error handling and left dummy outputs.",
        confidence=0.4,
        recommended_next_step="Builder must rewrite components correctly."
    ).model_dump_json()
    strong_mock.set_response_for_key("Verify this output for task", rejection_payload)

    router = ModelRouter(strong_adapter=strong_mock, cheap_adapter=cheap_mock)
    governor = CostGovernor(global_limit=10.0)
    registry = AgentRegistry()

    # Register Role configs
    registry.register_role(RoleConfig(
        name="backend_lead", domain="Backend Engineering", responsibilities=["Architecture", "Decomposition"], allowed_tools=["*"]
    ))
    registry.register_role(RoleConfig(
        name="backend_builder", domain="Backend Engineering", responsibilities=["Code development"], allowed_tools=["*"]
    ))
    registry.register_role(RoleConfig(
        name="backend_auditor", domain="Backend Engineering", responsibilities=["Independent review"], allowed_tools=["*"]
    ))

    # Register actual Agent identities with authority levels
    registry.register_agent(AgentIdentity(
        name="BackendLeadAgent", role="backend_lead", domain="Backend Engineering", authority_level=4, mission="Lead the backend pod", owner="CTO"
    ))
    registry.register_agent(AgentIdentity(
        name="BackendBuilderAgent", role="backend_builder", domain="Backend Engineering", authority_level=2, mission="Build backend components", owner="backend_lead"
    ))
    registry.register_agent(AgentIdentity(
        name="BackendAuditorAgent", role="backend_auditor", domain="Backend Engineering", authority_level=3, mission="Perform independent audits", owner="backend_lead"
    ))

    harness = VerificationHarness(event_bus=bus)

    # Re-register necessary pod structures
    backend_pod_def = PodDefinition(
        domain="Backend Engineering",
        lead_role="backend_lead",
        builder_roles=["backend_builder"],
        auditor_role="backend_auditor",
        definition_of_done=["Code syntax passes"],
        verification_method="auditor review",
        budget_ceiling=5.0
    )

    pod_runner = PodRunner(
        pod_def=backend_pod_def,
        agent_registry=registry,
        router=router,
        governor=governor,
        workflow_engine=workflow_engine,
        verification_harness=harness
    )

    task = workflow_engine.create_task("Test task", "Simple description", 2.0)
    success = pod_runner.execute_task(task.task_id)

    assert not success
    assert task.state == TaskState.ESCALATED
    assert task.retries == 3
