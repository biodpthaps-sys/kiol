# On-Demand Specialist Spawner and Teardown logic implementation

import time
from typing import List, Dict, Any, Optional
from council.core.schemas import TaskState, AgentOutputContract, QUALITY_DOCTRINE_V2
from council.core.registries import AgentRegistry, AgentIdentity, RoleConfig
from council.core.workflow import WorkflowEngine, Task
from council.core.governor import ModelRouter, CostGovernor
from council.core.orchestrator import VerificationHarness

class SpecialistSpawner:
    """
    Dynamically spawns, runs, and tears down specialist agents on-demand
    to cover narrow skills with zero idle overhead.
    """
    def __init__(self, agent_registry: AgentRegistry, router: ModelRouter,
                 governor: CostGovernor, workflow_engine: WorkflowEngine, verification_harness: VerificationHarness,
                 incident_manager: Optional[Any] = None, kb: Optional[Any] = None):
        self.agent_registry = agent_registry
        self.router = router
        self.governor = governor
        self.workflow_engine = workflow_engine
        self.verification_harness = verification_harness
        self.incident_manager = incident_manager
        self.kb = kb
        self.spawned_agents: List[str] = []

    def spawn_specialist(self, domain: str, role_name: str, mission: str,
                         tools: List[str], budget_ceiling: float, authority_level: int = 2) -> str:
        agent_name = f"Specialist_{role_name}_{int(time.time())}"

        # 1. Register Role config if not exists
        role_config = RoleConfig(
            name=role_name,
            domain=domain,
            responsibilities=[mission],
            allowed_tools=tools,
            default_model="cheap",
            max_budget_ceiling=budget_ceiling
        )
        self.agent_registry.register_role(role_config)

        # 2. Register Agent identity
        agent_id = AgentIdentity(
            name=agent_name,
            role=role_name,
            domain=domain,
            authority_level=authority_level,
            mission=mission,
            owner="Orchestrator",
            created_at=time.time(),
            revocation_status=False
        )
        self.agent_registry.register_agent(agent_id)

        self.spawned_agents.append(agent_name)
        return agent_name

    def _safe_record_cost(self, task_id: str, domain: str, cost: float, task_limit: Optional[float] = None) -> bool:
        """Safely record execution cost, catching budget breaches to escalate/block gracefully."""
        try:
            self.governor.record_cost(task_id, domain, cost, task_limit=task_limit)
            task = self.workflow_engine.get_task(task_id)
            if task:
                task.actual_cost = self.governor.task_spend.get(task_id, 0.0)
            return True
        except Exception as e:
            self.workflow_engine.transition_to(task_id, TaskState.BLOCKED, f"Budget breach: {str(e)}", kb=self.kb)
            if self.incident_manager:
                self.incident_manager.declare_incident(
                    pod_name=domain,
                    reason=f"Budget breach: {str(e)}",
                    rollback_plan_name="freeze_writes"
                )
            return False

    def execute_specialist_task(self, agent_name: str, task_id: str, auditor_agent_name: str, keep_alive: bool = False) -> bool:
        task = self.workflow_engine.get_task(task_id)
        if not task:
            return False

        agent = self.agent_registry.get_agent(agent_name)
        if not agent or agent.revocation_status:
            raise RuntimeError(f"Spawned specialist {agent_name} does not exist or has been revoked.")

        # Strict Permission check on the dynamic specialist
        from council.core.registries import PermissionEngine, ToolRegistry
        permission_engine = PermissionEngine(self.agent_registry, ToolRegistry())
        if not permission_engine.verify_action(agent_name, "write_file", ""):
            self.workflow_engine.transition_to(task_id, TaskState.FAILED, f"Permission Error: Specialist {agent_name} lacks build/write authority.", kb=self.kb)
            if not keep_alive:
                self.teardown_specialist(agent_name)
            return False

        # Phase C: Researching
        self.workflow_engine.transition_to(task_id, TaskState.RESEARCHING, f"Specialist {agent_name} researching task context", kb=self.kb)
        if not self._safe_record_cost(task_id, agent.domain, 0.01, task_limit=task.budget_ceiling):
            if not keep_alive:
                self.teardown_specialist(agent_name)
            return False

        # Step plan submission
        self.governor.submit_step_plan(task_id, estimated_tool_calls=3, estimated_cost=1.0)

        # Phase D: Building
        self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Specialist {agent_name} executing builds", kb=self.kb)

        system_prompt = f"You are {agent_name}.\n{QUALITY_DOCTRINE_V2}\nDomain: {agent.domain}.\nMission: {agent.mission}."
        user_prompt = f"Perform narrow-domain task: {task.name}. Details: {task.description}"

        adapter = self.router.get_adapter("cheap")

        success = False
        while task.retries < task.max_retries:
            task.retries += 1
            response_json = adapter.call_llm(system_prompt, user_prompt, response_format_schema=AgentOutputContract)
            if not self._safe_record_cost(task_id, agent.domain, 0.20, task_limit=task.budget_ceiling):
                if not keep_alive:
                    self.teardown_specialist(agent_name)
                return False
            self.governor.record_tool_call(task_id)

            try:
                contract = AgentOutputContract.model_validate_json(response_json)
            except Exception as e:
                self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Attempt {task.retries} output validation failed: {str(e)}", kb=self.kb)
                continue

            task.outputs = contract.model_dump()

            # Phase E/F: Critique & Verification
            self.workflow_engine.transition_to(task_id, TaskState.VERIFYING, f"Attempt {task.retries}: Performing specialist verification", kb=self.kb)

            auto_pass = self.verification_harness.run_automated_checks(task, contract.result)
            if not auto_pass:
                continue

            auditor_pass = self.verification_harness.run_auditor_review(
                task, auditor_agent_name, contract.result, self.router
            )
            if auditor_pass:
                success = True
                break
            else:
                self.workflow_engine.transition_to(task_id, TaskState.BUILDING, f"Attempt {task.retries} failed auditor review", kb=self.kb)

        if success:
            self.workflow_engine.transition_to(task_id, TaskState.COMPLETED, f"Specialist task completed and verified", kb=self.kb)
            if not keep_alive:
                self.teardown_specialist(agent_name)
            return True
        else:
            self.workflow_engine.transition_to(task_id, TaskState.ESCALATED, f"Specialist task failed verification after {task.max_retries} attempts", kb=self.kb)
            if self.incident_manager:
                self.incident_manager.raise_escalation(
                    task_id=task_id,
                    trigger_reason="3 failed verification attempts",
                    detail=f"Specialist task failed verification after {task.max_retries} attempts."
                )
            if not keep_alive:
                self.teardown_specialist(agent_name)
            return False

    def teardown_specialist(self, agent_name: str):
        """Tears down the specialist agent, revoking access and removing from active index."""
        if agent_name in self.spawned_agents:
            self.agent_registry.revoke_agent(agent_name)
            self.spawned_agents.remove(agent_name)
