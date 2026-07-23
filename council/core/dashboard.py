# Interactive Founder Console Dashboard and CLI report tool

import os
import sys
import time
from typing import Dict, Any, List, Optional
from council.core.schemas import TaskState
from council.core.workflow import WorkflowEngine, Task
from council.core.governor import CostGovernor
from council.core.knowledge import EscalationAndIncidentManager

class FounderDashboard:
    """
    Console dashboard rendering a live view of system status, active tasks,
    budgets, pending approvals, escalations, and incident alerts.
    """
    def __init__(self, workflow_engine: WorkflowEngine, governor: CostGovernor, incident_manager: EscalationAndIncidentManager):
        self.workflow_engine = workflow_engine
        self.governor = governor
        self.incident_manager = incident_manager

    def render_to_string(self) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append(" " * 28 + "THE COUNCIL - FOUNDER DASHBOARD")
        lines.append("=" * 80)

        # 1. System Health & Infrastructure status
        lines.append(f" [SYSTEM RUNTIME STATUS]  Active: YES  |  Storage: SQLite-Durable  |  Events: EventBus Online")
        lines.append("-" * 80)

        # 2. Cost Governance
        remaining = max(0.0, self.governor.global_limit - self.governor.global_spend)
        lines.append(f" [BUDGET STATUS]  Global Limit: ${self.governor.global_limit:,.2f}  |  Spent: ${self.governor.global_spend:,.2f}  |  Remaining: ${remaining:,.2f}")
        lines.append("-" * 80)

        # 3. Task Tracker
        lines.append(" [ACTIVE WORKFLOW TASKS] ")
        tasks = list(self.workflow_engine.tasks.values())
        if not tasks:
            lines.append("   (No tasks currently in workflow engine)")
        else:
            for task in tasks:
                parent_info = f" (Subtask of {task.parent_id[:8]})" if task.parent_id else " (Main Goal)"
                lines.append(f"   - [{task.state.value.upper()}] ID: {task.task_id[:8]}.. Name: '{task.name[:40]}' | Assigned: {task.assigned_to or 'Unassigned'}{parent_info}")
        lines.append("-" * 80)

        # 4. Escalation Alerts
        lines.append(" [ACTIVE ESCALATIONS] ")
        escalations = [e for e in self.incident_manager.escalations if not e["resolved"]]
        if not escalations:
            lines.append("   (No active escalations outstanding)")
        else:
            for esc in escalations:
                lines.append(f"   - [PENDING FOUNDER INPUT] EscID: {esc['escalation_id']} | Reason: {esc['trigger_reason']} | Detail: {esc['detail']}")
        lines.append("-" * 80)

        # 5. Incident & Rollbacks status
        lines.append(" [SYSTEM INCIDENTS & ROLLBACK LOG] ")
        active_incidents = [i for i in self.incident_manager.incidents.values() if i["status"] == "active"]
        if not active_incidents:
            lines.append("   (All pods running smoothly, zero active incidents)")
        else:
            for inc in active_incidents:
                rollback_status = "Executed" if inc["rollback_executed"] else "Not needed"
                lines.append(f"   - [ALERT: INCIDENT ACTIVE] Pod: {inc['pod_name']} | Reason: {inc['reason']} | Rollback: {rollback_status} ({inc['rollback_plan']})")
        lines.append("=" * 80)

        return "\n".join(lines)

    def display(self):
        print(self.render_to_string())

def run_dry_run_dashboard() -> str:
    """Helper to simulate an active workload and run the dashboard in mock mode."""
    # Build complete sandbox structures
    from council.core.knowledge import KnowledgeBase
    kb = KnowledgeBase()
    gov = CostGovernor(global_limit=50.0)
    workflow = WorkflowEngine()
    inc = EscalationAndIncidentManager(kb)

    # Simulate tasks
    t1 = workflow.create_task("Draft legal contracts", "Write agreement for Stripe integration", 15.0)
    workflow.transition_to(t1.task_id, TaskState.BUILDING)
    t1.assigned_to = "legal_builder"

    t2 = workflow.create_task("Verify API route coverage", "Audit coverage reports", 5.0, parent_id=t1.task_id)
    workflow.transition_to(t2.task_id, TaskState.ESCALATED)
    t2.assigned_to = "qa_builder"

    # Simulate costs
    gov.record_cost(t1.task_id, "Legal/Compliance", 2.50)
    gov.record_cost(t2.task_id, "QA/Test", 1.80)

    # Raise an escalation and declare an incident
    inc.raise_escalation(t2.task_id, "3 failed verification attempts", "Auditor continuously rejected the API route test outputs.")
    inc.declare_incident("QA/Test", "Container crash loop detected in test execution sandbox", "restart_worker_service")

    dashboard = FounderDashboard(workflow, gov, inc)
    rendered = dashboard.render_to_string()
    print(rendered)
    return rendered

if __name__ == "__main__":
    run_dry_run_dashboard()
