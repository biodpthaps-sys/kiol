# Acceptance Criteria - Gap Analysis Test Suite (v2.1 Patch)

import json
import pytest
from council.core.schemas import TaskState, AgentOutputContract
from council.core.registries import AgentRegistry, AgentIdentity, RoleConfig, ToolRegistry, PermissionEngine
from council.core.workflow import WorkflowEngine, Task
from council.core.governor import ModelRouter, MockLLMAdapter, CostGovernor, OpenAIModelAdapter, AnthropicModelAdapter
from council.core.orchestrator import GoalBrief, PodDefinition, VerificationHarness, PodRunner, Orchestrator
from council.core.knowledge import KnowledgeBase, EscalationAndIncidentManager
from council.core.specialist import SpecialistSpawner
from council.core.event_bus import EventBus

# --- CONFIRMED BEHAVIORS (Must keep passing) ---

def test_CONFIRMED_event_bus_delivery():
    bus = EventBus()
    events = []
    bus.subscribe("test.topic", lambda e: events.append(e))
    bus.publish("test.topic", "tester", {"status": "ok"})
    assert len(events) == 1
    assert events[0].payload["status"] == "ok"


def test_CONFIRMED_sqlite_compaction():
    kb = KnowledgeBase()
    kb.record_event("action.log", "builder", {"msg": "building"})
    count = kb.run_memory_compaction()
    assert count == 1
    kb.close()


# --- GAP TESTS (Must fail initially, and pass after fixes) ---

def test_GAP_no_approval_checkpoint_even_for_high_risk_goal():
    # Verify that a high-risk goal transitions task through AWAITING_APPROVAL and blocks on approval
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)
    registry = AgentRegistry()

    # Register agents so they are fully registered
    registry.register_role(RoleConfig(name="backend_lead", domain="Backend Engineering", responsibilities=["Lead"]))
    registry.register_role(RoleConfig(name="backend_builder", domain="Backend Engineering", responsibilities=["Builder"]))
    registry.register_role(RoleConfig(name="backend_auditor", domain="Backend Engineering", responsibilities=["Auditor"]))

    registry.register_agent(AgentIdentity(name="LeadAg", role="backend_lead", domain="Backend Engineering", authority_level=4, mission="L", owner="CTO"))
    registry.register_agent(AgentIdentity(name="BuildAg", role="backend_builder", domain="Backend Engineering", authority_level=2, mission="B", owner="Lead"))
    registry.register_agent(AgentIdentity(name="AuditAg", role="backend_auditor", domain="Backend Engineering", authority_level=3, mission="A", owner="Lead"))

    router = ModelRouter(MockLLMAdapter(), MockLLMAdapter())
    governor = CostGovernor()
    kb = KnowledgeBase()
    incident_manager = EscalationAndIncidentManager(kb)
    harness = VerificationHarness(event_bus=bus)

    orchestrator = Orchestrator(registry, router, governor, workflow_engine, harness, kb, incident_manager)

    pod_def = PodDefinition(
        domain="Backend Engineering",
        lead_role="backend_lead",
        builder_roles=["backend_builder"],
        auditor_role="backend_auditor",
        definition_of_done=["Done"],
        verification_method="audit",
        budget_ceiling=5.0
    )
    pod_runner = PodRunner(pod_def, registry, router, governor, workflow_engine, harness, incident_manager=incident_manager, kb=kb)
    orchestrator.register_pod(pod_runner)

    brief = GoalBrief(
        goal="High risk migration script",
        success_criteria=["No data loss"],
        risk_level="high",
        budget_ceiling=10.0
    )

    # By default, orchestrator should handle the goal, notice high risk, transition the task to AWAITING_APPROVAL, and pause.
    result = orchestrator.handle_goal(brief)
    assert result["status"] == "awaiting_approval"

    main_task = workflow_engine.get_task(result["main_task_id"])
    assert main_task.state == TaskState.AWAITING_APPROVAL

    # Provide explicit approval signal
    orchestrator.approve_goal(result["main_task_id"])

    # Verify main task proceeds and successfully completes
    assert main_task.state == TaskState.COMPLETED
    kb.close()


def test_GAP_risk_level_never_read_anywhere_in_execution_path():
    # Verify that risk_level changes tiered-compute selection
    cheap_mock = MockLLMAdapter("cheap-mock")
    strong_mock = MockLLMAdapter("strong-mock")
    router = ModelRouter(strong_mock, cheap_mock)

    # Router must dynamically select adapter based on risk_level or complexity
    # Low-risk task uses cheap, high-risk task uses strong
    adapter_low = router.route_by_context(risk_level="low", novelty=False)
    adapter_high = router.route_by_context(risk_level="high", novelty=False)

    assert adapter_low.model_name == "cheap-mock-model" or adapter_low == cheap_mock
    assert adapter_high.model_name == "strong-mock-model" or adapter_high == strong_mock


def test_GAP_automated_checks_miss_a_planted_logic_bug():
    # Verify that a planted logic bug fails automated verification
    harness = VerificationHarness()
    task = Task(name="logic test")

    # This deliverable looks syntactically correct but has a clear logic flaw
    broken_deliverable = """
    def compute_sum(a, b):
        return a - b  # WRONG OPERATION: Should be addition!
    """

    # We name a custom test function or validation script as the verification method
    # It should detect the logic flaw and return False, not fall back to simple string-matching
    task.name = "Verify compute_sum performs addition"
    passed = harness.run_automated_checks(task, broken_deliverable, verification_method="assert compute_sum(2, 3) == 5")
    assert passed is False


def test_GAP_auditor_review_ignores_deliverable_content_in_default_path():
    # Verify run_auditor_review evaluates deliverable content on substance
    cheap_mock = MockLLMAdapter("cheap")
    strong_mock = MockLLMAdapter("strong")

    # Set up auditor mock to reject the deliverable if it contains a logic bug
    bad_contract = AgentOutputContract(
        task_id="test",
        role="auditor",
        objective="audit",
        result="[REJECT] Code contains a logic bug.",
        confidence=0.3,
        recommended_next_step="Fix addition operator"
    ).model_dump_json()
    strong_mock.set_response_for_key("compute_sum(a, b):", bad_contract)

    router = ModelRouter(strong_mock, cheap_mock)
    harness = VerificationHarness()
    task = Task(name="Logic test")

    broken_deliverable = "def compute_sum(a, b): return a - b"
    passed = harness.run_auditor_review(task, "backend_auditor", broken_deliverable, router)
    assert passed is False


def test_GAP_permission_engine_fails_open_on_unrecognized_action_type():
    registry = AgentRegistry()
    registry.register_role(RoleConfig(name="builder", domain="D", responsibilities=["B"]))
    registry.register_agent(AgentIdentity(name="Agent1", role="builder", domain="D", authority_level=2, mission="M", owner="CTO"))

    engine = PermissionEngine(registry, ToolRegistry())

    # Unrecognized action types must be denied by default (Least-Privilege)
    allowed = engine.verify_action("Agent1", "unrecognized_hack_action", "resource")
    assert allowed is False


def test_GAP_podrunner_skips_permission_check_when_role_has_no_registered_agent():
    registry = AgentRegistry()
    # Ensure lead/builder roles are in config but NO agent identity is registered for them
    pod_def = PodDefinition(
        domain="Empty Domain",
        lead_role="unregistered_lead",
        builder_roles=["unregistered_builder"],
        auditor_role="unregistered_auditor",
        definition_of_done=["Done"],
        verification_method="audit",
        budget_ceiling=5.0
    )

    router = ModelRouter(MockLLMAdapter(), MockLLMAdapter())
    governor = CostGovernor()
    workflow_engine = WorkflowEngine()
    harness = VerificationHarness()

    runner = PodRunner(pod_def, registry, router, governor, workflow_engine, harness)
    task = workflow_engine.create_task("Protected Task", "Write code", 2.0)

    # Task should fail closed because no registered agent exists for the roles
    success = runner.execute_task(task.task_id)
    assert success is False
    assert task.state == TaskState.FAILED
    assert "no registered agent for role" in task.history[-1]["reason"]


def test_GAP_per_pod_budget_ceiling_is_not_enforced():
    # Verify that CostGovernor tracks and enforces per-pod limits
    governor = CostGovernor(global_limit=10.0)
    governor.set_pod_limit("QA Pod", 2.0)

    # Record cost within limit
    governor.record_cost("task1", "QA Pod", 1.5, pod_limit=2.0)

    # Record cost that breaches per-pod ceiling
    with pytest.raises(RuntimeError, match="Pod budget breached"):
        governor.record_cost("task2", "QA Pod", 1.0, pod_limit=2.0)


def test_GAP_budget_breach_raises_uncaught_exception_instead_of_graceful_stop():
    registry = AgentRegistry()
    registry.register_role(RoleConfig(name="lead", domain="D", responsibilities=["L"]))
    registry.register_role(RoleConfig(name="builder", domain="D", responsibilities=["B"]))
    registry.register_role(RoleConfig(name="auditor", domain="D", responsibilities=["A"]))
    registry.register_agent(AgentIdentity(name="Lead", role="lead", domain="D", authority_level=4, mission="M", owner="O"))
    registry.register_agent(AgentIdentity(name="Builder", role="builder", domain="D", authority_level=2, mission="M", owner="O"))
    registry.register_agent(AgentIdentity(name="Auditor", role="auditor", domain="D", authority_level=3, mission="M", owner="O"))

    pod_def = PodDefinition(
        domain="D", lead_role="lead", builder_roles=["builder"], auditor_role="auditor",
        definition_of_done=["Done"], verification_method="audit", budget_ceiling=1.0
    )

    # Setup governor that is already near its limit
    governor = CostGovernor(global_limit=10.0)
    governor.record_cost("other", "D", 0.9) # Spends 0.9 of pod ceiling 1.0

    kb = KnowledgeBase()
    incident_manager = EscalationAndIncidentManager(kb)
    workflow_engine = WorkflowEngine()
    harness = VerificationHarness()
    router = ModelRouter(MockLLMAdapter(), MockLLMAdapter())

    runner = PodRunner(pod_def, registry, router, governor, workflow_engine, harness, incident_manager=incident_manager, kb=kb)
    task = workflow_engine.create_task("Over budget task", "Build a big service", 1.0)

    # Running execution should handle the budget breach gracefully, transition task to BLOCKED / ESCALATED,
    # and notify the incident manager instead of crashing with uncaught RuntimeError.
    success = runner.execute_task(task.task_id)
    assert success is False
    assert task.state in [TaskState.BLOCKED, TaskState.ESCALATED]
    assert len(incident_manager.incidents) > 0 or len(incident_manager.escalations) > 0
    kb.close()


def test_GAP_escalation_manager_never_notified_when_a_real_task_escalates():
    registry = AgentRegistry()
    registry.register_role(RoleConfig(name="lead", domain="D", responsibilities=["L"]))
    registry.register_role(RoleConfig(name="builder", domain="D", responsibilities=["B"]))
    registry.register_role(RoleConfig(name="auditor", domain="D", responsibilities=["A"]))
    registry.register_agent(AgentIdentity(name="Lead", role="lead", domain="D", authority_level=4, mission="M", owner="O"))
    registry.register_agent(AgentIdentity(name="Builder", role="builder", domain="D", authority_level=2, mission="M", owner="O"))
    registry.register_agent(AgentIdentity(name="Auditor", role="auditor", domain="D", authority_level=3, mission="M", owner="O"))

    pod_def = PodDefinition(
        domain="D", lead_role="lead", builder_roles=["builder"], auditor_role="auditor",
        definition_of_done=["Done"], verification_method="audit", budget_ceiling=5.0
    )

    # Configure Auditor to reject always to force 3 retries and ESCALATE
    strong_mock = MockLLMAdapter("strong")
    rejected_contract = AgentOutputContract(
        task_id="test", role="auditor", objective="audit", result="[REJECT] Omitted critical items", confidence=0.3, recommended_next_step="Redo"
    ).model_dump_json()
    strong_mock.set_response_for_key("Verify this output", rejected_contract)

    router = ModelRouter(strong_mock, MockLLMAdapter())
    governor = CostGovernor()
    kb = KnowledgeBase()
    incident_manager = EscalationAndIncidentManager(kb)
    workflow_engine = WorkflowEngine()
    harness = VerificationHarness()

    runner = PodRunner(pod_def, registry, router, governor, workflow_engine, harness, incident_manager=incident_manager, kb=kb)
    task = workflow_engine.create_task("Failing task", "Try to run", 2.0)

    # When task hits 3 retries and escalates, it must be recorded in EscalationAndIncidentManager
    success = runner.execute_task(task.task_id)
    assert success is False
    assert task.state == TaskState.ESCALATED
    assert len(incident_manager.escalations) == 1
    assert incident_manager.escalations[0]["task_id"] == task.task_id
    kb.close()


def test_GAP_task_state_never_persisted_to_knowledge_base_during_real_execution():
    kb = KnowledgeBase()
    # In-process workflow engine + real pod execution loop
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)
    registry = AgentRegistry()

    # Register agents
    registry.register_role(RoleConfig(name="lead", domain="D", responsibilities=["L"]))
    registry.register_role(RoleConfig(name="builder", domain="D", responsibilities=["B"]))
    registry.register_role(RoleConfig(name="auditor", domain="D", responsibilities=["A"]))
    registry.register_agent(AgentIdentity(name="Lead", role="lead", domain="D", authority_level=4, mission="M", owner="O"))
    registry.register_agent(AgentIdentity(name="Builder", role="builder", domain="D", authority_level=2, mission="M", owner="O"))
    registry.register_agent(AgentIdentity(name="Auditor", role="auditor", domain="D", authority_level=3, mission="M", owner="O"))

    pod_def = PodDefinition(
        domain="D", lead_role="lead", builder_roles=["builder"], auditor_role="auditor",
        definition_of_done=["Done"], verification_method="audit", budget_ceiling=5.0
    )

    router = ModelRouter(MockLLMAdapter(), MockLLMAdapter())
    governor = CostGovernor()
    harness = VerificationHarness(event_bus=bus)
    incident_manager = EscalationAndIncidentManager(kb)

    runner = PodRunner(pod_def, registry, router, governor, workflow_engine, harness, incident_manager=incident_manager, kb=kb)
    task = workflow_engine.create_task("SQLite Persisted Task", "Task to persist", 2.0)

    # Connect knowledge base to workflow state changes
    # Every state transition must call kb.persist_task(task) automatically
    workflow_engine.transition_to(task.task_id, TaskState.ASSIGNED, "Assigned to Lead", kb=kb)

    # Let's check sqlite DB
    cursor = kb.conn.cursor()
    cursor.execute("SELECT state FROM structured_tasks WHERE task_id=?", (task.task_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == TaskState.ASSIGNED.value

    # Run whole pod execution and check terminal persistence
    runner.execute_task(task.task_id)
    cursor.execute("SELECT state FROM structured_tasks WHERE task_id=?", (task.task_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == TaskState.COMPLETED.value

    kb.close()


def test_GAP_phase3_pods_have_no_registered_agents_or_live_podrunner_anywhere():
    # Verify that loader reads pods_config.json and dynamically registers AgentIdentity & live PodRunner in Orchestrator
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)
    registry = AgentRegistry()
    router = ModelRouter(MockLLMAdapter(), MockLLMAdapter())
    governor = CostGovernor()
    harness = VerificationHarness()
    kb = KnowledgeBase()
    incident_manager = EscalationAndIncidentManager(kb)

    orchestrator = Orchestrator(registry, router, governor, workflow_engine, harness, kb, incident_manager)

    # Load and wire all 15 pods dynamically from config
    orchestrator.load_pods_from_config("config/pods_config.json")

    # Assert all 15 pods are registered
    assert len(orchestrator.pods) == 15

    # Assert role configs and agents are registered for Frontend Engineering
    agent = registry.get_agent("Agent_frontend_lead")
    assert agent is not None
    assert agent.domain == "Frontend Engineering"
    assert agent.authority_level == 4

    kb.close()


def test_GAP_state_machine_allows_illegal_transitions():
    engine = WorkflowEngine()
    task = engine.create_task("Machine Task", "Validate State Transitions", 2.0)

    # Normal sequential flow is allowed: queued -> briefed -> decomposed -> ...
    engine.transition_to(task.task_id, TaskState.BRIEFED, "Good")

    # Direct queued -> completed or jumping to terminal state illegally must raise ValueError
    with pytest.raises(ValueError, match="Illegal state transition"):
        engine.transition_to(task.task_id, TaskState.COMPLETED, "Bad jump")

    # Reviving a completed / terminal state must raise ValueError
    # Transition to terminal state (fail / completed) through proper path first
    # For testing, transition from briefed to failed/escalated is allowed
    engine.transition_to(task.task_id, TaskState.FAILED, "Terminal")

    with pytest.raises(ValueError, match="Illegal state transition"):
        engine.transition_to(task.task_id, TaskState.BUILDING, "Try to revive")


def test_GAP_specialist_not_automatically_torn_down_after_task_completes():
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)
    registry = AgentRegistry()
    router = ModelRouter(MockLLMAdapter(), MockLLMAdapter())
    governor = CostGovernor()
    harness = VerificationHarness()

    spawner = SpecialistSpawner(registry, router, governor, workflow_engine, harness)

    agent_name = spawner.spawn_specialist(
        domain="Rust", role_name="rust_expert", mission="Optimize memory layouts", tools=["cargo"], budget_ceiling=3.0
    )

    task = workflow_engine.create_task("Optimize", "Optimize struct padding", 2.0)

    # Execute specialist task. It must teardown/revoke the agent identity automatically on closure
    success = spawner.execute_specialist_task(agent_name, task.task_id, "rust_auditor")
    assert success is True

    # Verify agent revocation
    agent_info = registry.get_agent(agent_name)
    assert agent_info.revocation_status is True
    assert agent_name not in spawner.spawned_agents
