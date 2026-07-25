# State Machine and Workflow Engine definitions

import uuid
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from council.core.schemas import TaskState

@dataclass
class Task:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    assigned_to: Optional[str] = None # agent name
    state: TaskState = TaskState.QUEUED
    parent_id: Optional[str] = None
    subtasks: List[str] = field(default_factory=list) # subtask IDs
    budget_ceiling: float = 0.0
    actual_cost: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    retries: int = 0
    max_retries: int = 3
    history: List[Dict[str, Any]] = field(default_factory=list)

class WorkflowEngine:
    def __init__(self, event_bus=None):
        self.tasks: Dict[str, Task] = {}
        self.event_bus = event_bus

    def create_task(self, name: str, description: str, budget: float, parent_id: Optional[str] = None, inputs: Dict[str, Any] = None) -> Task:
        # Prevent circular dependencies in the task hierarchy
        if parent_id:
            curr_id = parent_id
            visited = set()
            while curr_id:
                if curr_id in visited:
                    raise ValueError("Circular dependency detected in task hierarchy!")
                visited.add(curr_id)
                parent_task = self.tasks.get(curr_id)
                if parent_task:
                    curr_id = parent_task.parent_id
                else:
                    break

        task = Task(
            name=name,
            description=description,
            budget_ceiling=budget,
            parent_id=parent_id,
            inputs=inputs or {}
        )
        self.tasks[task.task_id] = task
        if parent_id and parent_id in self.tasks:
            self.tasks[parent_id].subtasks.append(task.task_id)

        if self.event_bus:
            self.event_bus.publish(
                topic=f"task.{task.task_id}.created",
                source="workflow_engine",
                payload={"task_id": task.task_id, "name": task.name, "state": task.state}
            )
        return task

    def transition_to(self, task_id: str, new_state: TaskState, reason: str = ""):
        if task_id not in self.tasks:
            return
        task = self.tasks[task_id]
        old_state = task.state
        task.state = new_state
        task.updated_at = time.time()

        log_entry = {
            "timestamp": task.updated_at,
            "old_state": old_state.value,
            "new_state": new_state.value,
            "reason": reason
        }
        task.history.append(log_entry)

        if self.event_bus:
            self.event_bus.publish(
                topic=f"task.{task_id}.state_changed",
                source="workflow_engine",
                payload={
                    "task_id": task_id,
                    "old_state": old_state.value,
                    "new_state": new_state.value,
                    "reason": reason
                }
            )

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)
