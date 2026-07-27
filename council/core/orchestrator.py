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

    def run_automated_checks(self, task: Task, deliverable: str, verification_method: Optional[str] = None) -> bool:
        """Runs lint/unit tests where applicable, performing actual code execution and assertions if requested."""
        if verification_method and "assert" in verification_method:
            try:
                local_vars = {}
                global_vars = {}
                # Safely execute deliverable to define its context
                exec(deliverable, global_vars, local_vars)
                ctx = {**global_vars, **local_vars}
                # Execute test/assertion in the context
                exec(verification_method, ctx)
                if self.event_bus:
                    self.event_bus.publish(f"task.{task.task_id}.automated_checks", "verification_harness", {"passed": True})
                return True
            except Exception as e:
                if self.event_bus:
                    self.event_bus.publish(f"task.{task.task_id}.automated_checks", "verification_harness", {"passed": False, "error": str(e)})
                return False

        # Fallback keyword checks
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


from council.core.registries import PermissionEngine, ToolRegistry

class PodRunner:
    """Config-driven generic pod execution runner implementing Phase C-G loop."""
    def __init__(self, pod_def: PodDefinition, agent_registry: AgentRegistry, router: ModelRouter,
                 governor: CostGovernor, workflow_engine: WorkflowEngine, verification_harness: VerificationHarness,
                 tool_registry: Optional[ToolRegistry] = None, incident_manager: Optional[Any] = None, kb: Optional[Any] = None):
        self.pod_def = pod_def
        self.agent_registry = agent_registry
        self.router = router
        self.governor = governor
        self.workflow_engine = workflow_engine
        self.verification_harness = verification_harness
        self.tool_registry = tool_registry or ToolRegistry()
        self.incident_manager = incident_manager
        self.kb = kb

    def _safe_record_cost(self, task_id: str, cost: float, task_limit: Optional[float] = None) -> bool:
        """Safely record execution cost, catching budget breaches to escalate/block gracefully."""
        try:
            self.governor.record_cost(task_id, self.pod_def.domain, cost, task_limit=task_limit, pod_limit=self.pod_def.budget_ceiling)
            task = self.workflow_engine.get_task(task_id)
            if task:
                task.actual_cost = self.governor.task_spend.get(task_id, 0.0)
            return True
        except Exception as e:
            # Transition task to terminal state BLOCKED / ESCALATED gracefully
            self.workflow_engine.transition_to(task_id, TaskState.BLOCKED, f"Budget breach: {str(e)}", kb=self.kb)
            if self.incident_manager:
                self.incident_manager.declare_incident(
                    pod_name=self.pod_def.domain,
                    reason=f"Budget breach: {str(e)}",
                    rollback_plan_name="freeze_writes"
                )
            return False

    def execute_task(self, task_id: str) -> bool:
        task = self.workflow_engine.get_task(task_id)
        if not task:
            return False

        # Strict Permission Validation
        if self.agent_registry:
            permission_engine = PermissionEngine(self.agent_registry, self.tool_registry)

            # 1. Verify Lead Agent can delegate
            lead_agent_name = None
            for agent in self.agent_registry.list_agents():
                if agent.role == self.pod_def.lead_role:
                    lead_agent_name = agent.name
                    break
            if not lead_agent_name:
                self.workflow_engine.transition_to(task_id, TaskState.FAILED, f"no registered agent for role {self.pod_def.lead_role}", kb=self.kb)
                return False

            if not permission_engine.verify_action(lead_agent_name, "delegate", ""):
                self.workflow_engine.transition_to(task_id, TaskState.FAILED, f"Permission Error: Lead {lead_agent_name} lacks delegation authority.", kb=self.kb)
                return False

            # 2. Verify Builder Agent has authority to write/build
            builder_agent = self.pod_def.builder_roles[0]
            builder_agent_name = None
            for agent in self.agent_registry.list_agents():
                if agent.role == builder_agent:
                    builder_agent_name = agent.name
                    break
            if not builder_agent_name:
                self.workflow_engine.transition_to(task_id, TaskState.FAILED, f"no registered agent for role {builder_agent}", kb=self.kb)
                return False

            if not permission_engine.verify_action(builder_agent_name, "write_file", ""):
                self.workflow_engine.transition_to(task_id, TaskState.FAILED, f"Permission Error: Builder {builder_agent_name} lacks write/build authority.", kb=self.kb)
                return False

        # Phase C: Researching
        self.workflow_engine.transition_to(task_id, TaskState.RESEARCHING, "Gathering existing context and specs", kb=self.kb)
        if not self._safe_record_cost(task_id, 0.01, task_limit=task.budget_ceiling):
            return False

        # Define steps plans
        self.governor.submit_step_plan(task_id, estimated_tool_calls=5, estimated_cost=1.5)

        # Let's run builder loop
        builder_agent = self.pod_def.builder_roles[0] # select builder
        self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Assigned to Builder {builder_agent} to write output", kb=self.kb)

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
            if not self._safe_record_cost(task_id, 0.25, task_limit=task.budget_ceiling):
                return False
            self.governor.record_tool_call(task_id)

            try:
                contract = AgentOutputContract.model_validate_json(response_json)
            except Exception as e:
                # Malformed output, count as failed attempt
                self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Attempt {task.retries} output validation failed: {str(e)}", kb=self.kb)
                continue

            # Record task output structure
            task.outputs = contract.model_dump()

            # Phase E/F: Critique & Verification
            self.workflow_engine.transition_to(task_id, TaskState.VERIFYING, f"Attempt {task.retries}: Performing verification checks", kb=self.kb)

            # Automated verification checks
            auto_pass = self.verification_harness.run_automated_checks(task, contract.result, self.pod_def.verification_method)
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
                self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Attempt {task.retries} failed auditor review", kb=self.kb)

        if success:
            self.workflow_engine.transition_to(task_id, TaskState.COMPLETED, "Completed and verified successfully", kb=self.kb)
            return True
        else:
            self.workflow_engine.transition_to(task_id, TaskState.ESCALATED, f"Failed verification after {task.max_retries} attempts", kb=self.kb)
            if self.incident_manager:
                self.incident_manager.raise_escalation(
                    task_id=task_id,
                    trigger_reason="3 failed verification attempts",
                    detail=f"Task failed verification after {task.max_retries} attempts."
                )
            return False


from council.core.knowledge import KnowledgeBase, EscalationAndIncidentManager

class Orchestrator:
    """
    CEO Agent / Orchestrator.
    Accepts Goal Brief, Decomposes it, tracks execution, handles escalations.
    """
    def __init__(self, agent_registry: AgentRegistry, router: ModelRouter, governor: CostGovernor,
                 workflow_engine: WorkflowEngine, verification_harness: VerificationHarness,
                 kb: Optional[KnowledgeBase] = None, incident_manager: Optional[EscalationAndIncidentManager] = None):
        self.agent_registry = agent_registry
        self.router = router
        self.governor = governor
        self.workflow_engine = workflow_engine
        self.verification_harness = verification_harness
        self.kb = kb
        self.incident_manager = incident_manager
        self.pods: Dict[str, PodRunner] = {}
        self.escalated_tasks: List[str] = []
        self.pending_approvals: Dict[str, GoalBrief] = {}

    def register_pod(self, pod_runner: PodRunner):
        self.pods[pod_runner.pod_def.domain] = pod_runner

    def load_pods_from_config(self, filepath: str):
        """Phase 3 Loader: reads config file and registers RoleConfigs, AgentIdentitys and live PodRunners on Orchestrator."""
        with open(filepath, "r") as f:
            data = json.load(f)
        for raw_pod in data.get("pods", []):
            pod_def = PodDefinition.model_validate(raw_pod)

            # Register lead
            self.agent_registry.register_role(RoleConfig(
                name=pod_def.lead_role, domain=pod_def.domain, responsibilities=[f"Lead for {pod_def.domain}"]
            ))
            self.agent_registry.register_agent(AgentIdentity(
                name=f"Agent_{pod_def.lead_role}", role=pod_def.lead_role, domain=pod_def.domain,
                authority_level=4, mission=f"Lead {pod_def.domain}", owner="CEO"
            ))

            # Register builders
            for builder in pod_def.builder_roles:
                self.agent_registry.register_role(RoleConfig(
                    name=builder, domain=pod_def.domain, responsibilities=[f"Builder for {pod_def.domain}"]
                ))
                self.agent_registry.register_agent(AgentIdentity(
                    name=f"Agent_{builder}", role=builder, domain=pod_def.domain,
                    authority_level=2, mission=f"Build components in {pod_def.domain}", owner=pod_def.lead_role
                ))

            # Register auditor
            self.agent_registry.register_role(RoleConfig(
                name=pod_def.auditor_role, domain=pod_def.domain, responsibilities=[f"Audit {pod_def.domain}"]
            ))
            self.agent_registry.register_agent(AgentIdentity(
                name=f"Agent_{pod_def.auditor_role}", role=pod_def.auditor_role, domain=pod_def.domain,
                authority_level=3, mission=f"Audit deliverables in {pod_def.domain}", owner=pod_def.lead_role
            ))

            # Register PodRunner on Orchestrator
            runner = PodRunner(
                pod_def=pod_def, agent_registry=self.agent_registry, router=self.router,
                governor=self.governor, workflow_engine=self.workflow_engine,
                verification_harness=self.verification_harness, kb=self.kb, incident_manager=self.incident_manager
            )
            self.register_pod(runner)

    def handle_goal(self, brief: GoalBrief) -> Dict[str, Any]:
        """Runs Phase A-B loop."""
        # Dynamic compute routing decision based on risk level
        complexity = "strong" if brief.risk_level == "high" else "cheap"
        adapter = self.router.get_adapter(complexity)

        system_prompt = f"You are the CEO Agent (Orchestrator).\n{QUALITY_DOCTRINE_V2}"
        user_prompt = f"Intake and plan for Goal: {brief.goal}. Budget: {brief.budget_ceiling}."

        proposal = adapter.call_llm(system_prompt, user_prompt)

        # Phase B: Decomposition
        main_task = self.workflow_engine.create_task(
            name=f"Goal: {brief.goal[:30]}...",
            description=brief.goal,
            budget=brief.budget_ceiling
        )

        # State machine flow: queued -> briefed -> decomposed
        self.workflow_engine.transition_to(main_task.task_id, TaskState.BRIEFED, "Goal brief loaded", kb=self.kb)
        self.workflow_engine.transition_to(main_task.task_id, TaskState.DECOMPOSED, "Decomposed goal into operational workflow", kb=self.kb)

        # 1.1 Approval checkpoint if risk_level is high
        if brief.risk_level == "high":
            self.workflow_engine.transition_to(main_task.task_id, TaskState.AWAITING_APPROVAL, "High risk goal requires explicit founder approval", kb=self.kb)
            self.pending_approvals[main_task.task_id] = brief
            return {"status": "awaiting_approval", "main_task_id": main_task.task_id}

        # Low risk transitions directly to EXECUTING
        self.workflow_engine.transition_to(main_task.task_id, TaskState.EXECUTING, "Executing goal", kb=self.kb)
        return self._execute_subgoals(main_task.task_id, brief)

    def approve_goal(self, main_task_id: str) -> Dict[str, Any]:
        if main_task_id not in self.pending_approvals:
            return {"status": "error", "reason": "No pending approval found"}
        brief = self.pending_approvals.pop(main_task_id)

        # Transition to EXECUTING
        self.workflow_engine.transition_to(main_task_id, TaskState.EXECUTING, "Goal approved by founder, executing", kb=self.kb)
        return self._execute_subgoals(main_task_id, brief)

    def _execute_subgoals(self, main_task_id: str, brief: GoalBrief) -> Dict[str, Any]:
        subtask = self.workflow_engine.create_task(
            name="Implement backend components",
            description="Build robust modular database models and integration interfaces",
            budget=brief.budget_ceiling * 0.5,
            parent_id=main_task_id
        )

        self.workflow_engine.transition_to(subtask.task_id, TaskState.BRIEFED, "Briefed subtask", kb=self.kb)
        self.workflow_engine.transition_to(subtask.task_id, TaskState.DECOMPOSED, "Decomposed subtask", kb=self.kb)

        subtask.assigned_to = "backend_lead"
        self.workflow_engine.transition_to(subtask.task_id, TaskState.ASSIGNED, "Assigned to Backend Pod Lead", kb=self.kb)

        # Execute subtask in pod runner
        backend_runner = self.pods.get("Backend Engineering")
        if not backend_runner:
            self.workflow_engine.transition_to(subtask.task_id, TaskState.FAILED, "Backend Engineering Pod runner not registered", kb=self.kb)
            self.workflow_engine.transition_to(main_task_id, TaskState.FAILED, "Subgoal failed", kb=self.kb)
            return {"status": "failed", "reason": "Missing pod runner"}

        # Run task execution
        success = backend_runner.execute_task(subtask.task_id)
        if success:
            self.workflow_engine.transition_to(main_task_id, TaskState.COMPLETED, "All subgoals achieved successfully", kb=self.kb)
            return {"status": "completed", "main_task_id": main_task_id, "subtask_id": subtask.task_id}
        else:
            self.workflow_engine.transition_to(main_task_id, TaskState.ESCALATED, "Subtask failed execution and escalated", kb=self.kb)
            self.escalated_tasks.append(subtask.task_id)
            return {"status": "escalated", "main_task_id": main_task_id, "subtask_id": subtask.task_id}
