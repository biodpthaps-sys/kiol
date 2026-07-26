# Tests verifying security and logic upgrades (PermissionEngine blocks unauthorized tasks, compaction, and DAG validation)

import pytest
from council.core.schemas import TaskState
from council.core.registries import AgentRegistry, AgentIdentity, RoleConfig
from council.core.workflow import WorkflowEngine
from council.core.governor import ModelRouter, MockLLMAdapter, CostGovernor, OpenAIModelAdapter, AnthropicModelAdapter
from council.core.orchestrator import PodDefinition, VerificationHarness, PodRunner
from council.core.event_bus import EventBus
from council.core.knowledge import KnowledgeBase

def test_permission_engine_blocking_unauthorized_builder():
    bus = EventBus()
    workflow_engine = WorkflowEngine(event_bus=bus)
    registry = AgentRegistry()

    # Register Lead and Auditor roles with adequate authority
    registry.register_role(RoleConfig(name="lead_role", domain="Test Domain", responsibilities=["Lead"]))
    registry.register_role(RoleConfig(name="builder_role", domain="Test Domain", responsibilities=["Builder"]))
    registry.register_role(RoleConfig(name="auditor_role", domain="Test Domain", responsibilities=["Auditor"]))

    registry.register_agent(AgentIdentity(name="LeadAgent", role="lead_role", domain="Test Domain", authority_level=4, mission="Lead", owner="CTO"))
    registry.register_agent(AgentIdentity(name="AuditorAgent", role="auditor_role", domain="Test Domain", authority_level=3, mission="Audit", owner="lead_role"))

    # Register an UNAUTHORIZED builder agent (authority level 0, which cannot write_file)
    registry.register_agent(AgentIdentity(name="BadBuilder", role="builder_role", domain="Test Domain", authority_level=0, mission="Build", owner="lead_role"))

    pod_def = PodDefinition(
        domain="Test Domain",
        lead_role="lead_role",
        builder_roles=["builder_role"],
        auditor_role="auditor_role",
        definition_of_done=["Done"],
        verification_method="audit",
        budget_ceiling=5.0
    )

    cheap_mock = MockLLMAdapter("cheap-mock")
    strong_mock = MockLLMAdapter("strong-mock")
    router = ModelRouter(strong_adapter=strong_mock, cheap_adapter=cheap_mock)
    governor = CostGovernor(global_limit=10.0)
    harness = VerificationHarness(event_bus=bus)

    runner = PodRunner(pod_def, registry, router, governor, workflow_engine, harness)
    task = workflow_engine.create_task("Protected Task", "Build security component", 2.0)

    # Execute task and ensure it fails because of permission denial
    success = runner.execute_task(task.task_id)
    assert success is False
    assert task.state == TaskState.FAILED
    assert "Permission Error" in task.history[-1]["reason"]
    print("Permission Engine blocks unauthorized builders successfully!")


def test_upgraded_compaction_pruning_and_archival():
    kb = KnowledgeBase()

    # Insert raw events into the immutable store
    kb.record_event("action.write", "builder_1", {"file": "core.py"})
    kb.record_event("action.audit", "auditor_1", {"status": "passed"})

    # Check that there are 2 events in store
    cursor = kb.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM event_store")
    assert cursor.fetchone()[0] == 2

    # Execute dynamic compaction
    count_compacted = kb.run_memory_compaction()
    assert count_compacted == 2

    # Check that event_store table has been cleanly pruned to save space and prevent memory leaks
    cursor.execute("SELECT COUNT(*) FROM event_store")
    assert cursor.fetchone()[0] == 0

    # Verify that details are stored as a consolidated document archive
    cursor.execute("SELECT content FROM documents WHERE doc_id='compaction_latest'")
    doc_content = cursor.fetchone()[0]
    assert "Memory Compaction executed successfully" in doc_content
    assert "action.write" in doc_content
    assert "action.audit" in doc_content

    kb.close()
    print("Upgraded compaction prunes and archives raw logs successfully!")


def test_production_adapters_fallback_offline():
    # OpenAI model adapter fallback to Mock
    openai_adapter = OpenAIModelAdapter(api_key=None)
    res_openai = openai_adapter.call_llm("System info", "Hello OpenAI")
    assert "mock-model" in res_openai or "success" in res_openai or "mocked" in res_openai

    # Anthropic model adapter fallback to Mock
    anthropic_adapter = AnthropicModelAdapter(api_key=None)
    res_anthropic = anthropic_adapter.call_llm("System info", "Hello Anthropic")
    assert "mock-model" in res_anthropic or "success" in res_anthropic or "mocked" in res_anthropic

    print("Production adapters fall back cleanly in offline mode!")


def test_workflow_circular_dependency_detection():
    engine = WorkflowEngine()

    # Create task A
    task_a = engine.create_task("Task A", "First task", 1.0)

    # Create task B with parent A
    task_b = engine.create_task("Task B", "Second task", 1.0, parent_id=task_a.task_id)

    # Manually create a loop back in task_a parent to simulate external manipulation or bad graph definition
    task_a.parent_id = task_b.task_id

    # Try creating task C pointing to task A, which should trigger the validation cycle detection
    with pytest.raises(ValueError, match="Circular dependency detected"):
        engine.create_task("Task C", "Third task", 1.0, parent_id=task_a.task_id)

    print("Workflow circular dependency detection blocks loops successfully!")
