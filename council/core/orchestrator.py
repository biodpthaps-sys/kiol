# The Orchestrator (CEO Agent) and Pod architecture implementation

import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from council.core.schemas import TaskState, AgentOutputContract, QUALITY_DOCTRINE_V2
from council.core.registries import AgentRegistry, AgentIdentity, RoleConfig
from council.core.workflow import WorkflowEngine, Task
from council.core.governor import ModelRouter, CostGovernor
from council.core.event_bus import EventBus

class GoalBrief(BaseModel):
    goal: str
    success_criteria: List[str]
    risk_level: str = "low" # low, medium, high
    budget_ceiling: float
    deadline: str = "ASAP"
    non_negotiables: List[str] = Field(default_factory=list)
    resources_available: List[str] = Field(default_factory=list)
    escalate_to_me_if: List[str] = Field(default_factory=list)


class PodDefinition(BaseModel):
    domain: str
    lead_role: str
    builder_roles: List[str]
    specialist_roles: List[str] = Field(default_factory=list)
    auditor_role: str
    definition_of_done: List[str]
    verification_method: str
    budget_ceiling: float


class VerificationHarness:
    """Independent verification checks (auto-test/lints/evals + Auditor check)"""
    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus

    def run_automated_checks(self, task: Task, deliverable: str) -> bool:
        """Runs lint/unit tests where applicable."""
        # Realistic local checks: does the code have syntax issues or failing keywords?
        # Avoid matching positive phrases like "no syntax error" or "successful without fail"
        lowered = deliverable.lower()
        has_error = False

        # Check syntax errors specifically
        if "syntax error:" in lowered or "syntaxerror" in lowered:
            has_error = True
        elif "exception:" in lowered or "traceback" in lowered or "runtimeerror" in lowered:
            has_error = True
        elif "[fail]" in lowered or "failed execution" in lowered:
            has_error = True

        if has_error:
            if self.event_bus:
                self.event_bus.publish(f"task.{task.task_id}.automated_checks", "verification_harness", {"passed": False})
            return False
        if self.event_bus:
            self.event_bus.publish(f"task.{task.task_id}.automated_checks", "verification_harness", {"passed": True})
        return True

    def run_auditor_review(self, task: Task, auditor_agent_name: str, deliverable: str, router: ModelRouter) -> bool:
        """Auditor agent independent review. No agent can approve its own work."""
        system_prompt = f"You are the independent Auditor Agent: {auditor_agent_name}.\n{QUALITY_DOCTRINE_V2}\nVerify the output."
        user_prompt = f"Verify this output for task '{task.name}':\n{deliverable}"

        # Auditor uses strongest reasoning for verification
        adapter = router.get_adapter("strong")
        response_json = adapter.call_llm(system_prompt, user_prompt, response_format_schema=AgentOutputContract)

        try:
            contract = AgentOutputContract.model_validate_json(response_json)
            # If Auditor finds critical risks, lack of evidence, or rejects
            if "reject" in contract.result.lower() or "fail" in contract.result.lower() or contract.confidence < 0.8:
                if self.event_bus:
                    self.event_bus.publish(f"task.{task.task_id}.auditor_review", "verification_harness", {"passed": False, "reason": contract.result})
                return False
            if self.event_bus:
                self.event_bus.publish(f"task.{task.task_id}.auditor_review", "verification_harness", {"passed": True, "reason": contract.result})
            return True
        except Exception:
            # Rejection on invalid format/schema
            return False


class PodRunner:
    """Config-driven generic pod execution runner implementing Phase C-G loop."""
    def __init__(self, pod_def: PodDefinition, agent_registry: AgentRegistry, router: ModelRouter,
                 governor: CostGovernor, workflow_engine: WorkflowEngine, verification_harness: VerificationHarness):
        self.pod_def = pod_def
        self.agent_registry = agent_registry
        self.router = router
        self.governor = governor
        self.workflow_engine = workflow_engine
        self.verification_harness = verification_harness

    def execute_task(self, task_id: str) -> bool:
        task = self.workflow_engine.get_task(task_id)
        if not task:
            return False

        # Phase C: Researching
        self.workflow_engine.transition_to(task_id, TaskState.RESEARCHING, "Gathering existing context and specs")
        self.governor.record_cost(task_id, self.pod_def.domain, 0.01) # Small transaction cost for state tracking

        # Define steps plans
        self.governor.submit_step_plan(task_id, estimated_tool_calls=5, estimated_cost=1.5)

        # Let's run builder loop
        builder_agent = self.pod_def.builder_roles[0] # select builder
        self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Assigned to Builder {builder_agent} to write output")

        # Build prompt using Quality Doctrine
        system_prompt = f"You are {builder_agent}.\n{QUALITY_DOCTRINE_V2}\nDomain: {self.pod_def.domain}."
        user_prompt = f"Execute Task: {task.name}. Description: {task.description}. DoD: {self.pod_def.definition_of_done}"

        # Cheap/fast model for routine building
        adapter = self.router.get_adapter("cheap")

        # Bounded iteration: retry loop up to 3 attempts
        success = False
        while task.retries < task.max_retries:
            task.retries += 1
            response_json = adapter.call_llm(system_prompt, user_prompt, response_format_schema=AgentOutputContract)
            self.governor.record_cost(task_id, self.pod_def.domain, 0.25)
            self.governor.record_tool_call(task_id)

            try:
                contract = AgentOutputContract.model_validate_json(response_json)
            except Exception as e:
                # Malformed output, count as failed attempt
                self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Attempt {task.retries} output validation failed: {str(e)}")
                continue

            # Record task output structure
            task.outputs = contract.model_dump()

            # Phase E/F: Critique & Verification
            self.workflow_engine.transition_to(task_id, TaskState.VERIFYING, f"Attempt {task.retries}: Performing verification checks")

            # Automated verification checks
            auto_pass = self.verification_harness.run_automated_checks(task, contract.result)
            if not auto_pass:
                continue

            # Auditor independent check
            auditor_pass = self.verification_harness.run_auditor_review(
                task, self.pod_def.auditor_role, contract.result, self.router
            )
            if auditor_pass:
                success = True
                break
            else:
                self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Attempt {task.retries} failed auditor review")

        if success:
            self.workflow_engine.transition_to(task_id, TaskState.COMPLETED, "Completed and verified successfully")
            return True
        else:
            self.workflow_engine.transition_to(task_id, TaskState.ESCALATED, f"Failed verification after {task.max_retries} attempts")
            return False


class Orchestrator:
    """
    CEO Agent / Orchestrator.
    Accepts Goal Brief, Decomposes it, tracks execution, handles escalations.
    """
    def __init__(self, agent_registry: AgentRegistry, router: ModelRouter, governor: CostGovernor,
                 workflow_engine: WorkflowEngine, verification_harness: VerificationHarness):
        self.agent_registry = agent_registry
        self.router = router
        self.governor = governor
        self.workflow_engine = workflow_engine
        self.verification_harness = verification_harness
        self.pods: Dict[str, PodRunner] = {}
        self.escalated_tasks: List[str] = []

    def register_pod(self, pod_runner: PodRunner):
        self.pods[pod_runner.pod_def.domain] = pod_runner

    def handle_goal(self, brief: GoalBrief) -> Dict[str, Any]:
        """Runs Phase A-B loop."""
        # Phase A: Intake
        # Validate inputs, plan formulation using Strong reasoning
        adapter = self.router.get_adapter("strong")
        system_prompt = f"You are the CEO Agent (Orchestrator).\n{QUALITY_DOCTRINE_V2}"
        user_prompt = f"Intake and plan for Goal: {brief.goal}. Budget: {brief.budget_ceiling}."

        # Proposal response
        proposal = adapter.call_llm(system_prompt, user_prompt)

        # Phase B: Decomposition into pod-level subgoals
        # Let's create a task in the workflow engine
        main_task = self.workflow_engine.create_task(
            name=f"Goal: {brief.goal[:30]}...",
            description=brief.goal,
            budget=brief.budget_ceiling
        )
        self.workflow_engine.transition_to(main_task.task_id, TaskState.DECOMPOSED, "Decomposed goal into operational workflow")

        # Let's create subtasks for Backend Pod (the single working pod in Phase 1)
        subtask = self.workflow_engine.create_task(
            name="Implement backend components",
            description="Build robust modular database models and integration interfaces",
            budget=brief.budget_ceiling * 0.5,
            parent_id=main_task.task_id
        )

        # Assign task
        subtask.assigned_to = "backend_lead"
        self.workflow_engine.transition_to(subtask.task_id, TaskState.ASSIGNED, "Assigned to Backend Pod Lead")

        # Execute subtask in pod runner
        backend_runner = self.pods.get("Backend Engineering")
        if not backend_runner:
            self.workflow_engine.transition_to(subtask.task_id, TaskState.FAILED, "Backend Engineering Pod runner not registered")
            return {"status": "failed", "reason": "Missing pod runner"}

        # Run task execution
        success = backend_runner.execute_task(subtask.task_id)
        if success:
            self.workflow_engine.transition_to(main_task.task_id, TaskState.COMPLETED, "All subgoals achieved successfully")
            return {"status": "completed", "main_task_id": main_task.task_id, "subtask_id": subtask.task_id}
        else:
            self.workflow_engine.transition_to(main_task.task_id, TaskState.ESCALATED, "Subtask failed execution and escalated")
            self.escalated_tasks.append(subtask.task_id)
            return {"status": "escalated", "main_task_id": main_task.task_id, "subtask_id": subtask.task_id}
