# Registries for Agents, Roles, Tools, Capabilities and Permissions

import time
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class ToolSchema(BaseModel):
    name: str
    description: str
    expected_inputs: Dict[str, Any]
    expected_outputs: Dict[str, Any]
    failure_modes: List[str] = Field(default_factory=list)
    retry_policy: Dict[str, Any] = Field(default_factory=dict)

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSchema] = {}

    def register_tool(self, tool: ToolSchema):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolSchema]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSchema]:
        return list(self._tools.values())


class RoleConfig(BaseModel):
    name: str
    domain: str
    responsibilities: List[str]
    allowed_tools: List[str] = Field(default_factory=list)
    default_model: str = "cheap"
    max_budget_ceiling: float = 10.0 # Default budget ceiling in USD/credits/tokens


class AgentIdentity(BaseModel):
    name: str
    role: str
    domain: str
    authority_level: int = Field(0, ge=0, le=5)
    mission: str
    owner: str # owning exec/pod
    created_at: float = Field(default_factory=time.time)
    revocation_status: bool = False


class AgentRegistry:
    def __init__(self):
        self._agents: Dict[str, AgentIdentity] = {}
        self._roles: Dict[str, RoleConfig] = {}

    def register_role(self, role: RoleConfig):
        self._roles[role.name] = role

    def get_role(self, name: str) -> Optional[RoleConfig]:
        return self._roles.get(name)

    def register_agent(self, agent: AgentIdentity):
        self._agents[agent.name] = agent

    def get_agent(self, name: str) -> Optional[AgentIdentity]:
        return self._agents.get(name)

    def revoke_agent(self, name: str):
        if name in self._agents:
            # Recreate with updated status to maintain immutability / Pydantic validation if needed
            agent = self._agents[name]
            updated_agent = agent.model_copy(update={"revocation_status": True})
            self._agents[name] = updated_agent

    def list_agents(self) -> List[AgentIdentity]:
        return list(self._agents.values())


class PermissionEngine:
    def __init__(self, agent_registry: AgentRegistry, tool_registry: ToolRegistry):
        self.agent_registry = agent_registry
        self.tool_registry = tool_registry

    def verify_action(self, agent_name: str, action_type: str, resource: str, context: Dict[str, Any] = None) -> bool:
        """
        Check if an agent has permission to run a specific action/tool on a resource.
        Authority levels:
        0 - Read-only: research, analysis, no writes
        1 - Draft only: produce, cannot ship, send, or merge
        2 - Execute reversible actions: branch commits, saved drafts, no external effect
        3 - Execute approved production changes, only within approved plan and verification
        4 - Department manager: budget + delegation authority within pod
        5 - Executive: coordinates across pods, can request Founder approval
        """
        agent = self.agent_registry.get_agent(agent_name)
        if not agent:
            return False
        if agent.revocation_status:
            return False

        # If action_type represents a tool execution
        if action_type == "execute_tool":
            tool = self.tool_registry.get_tool(resource)
            if not tool:
                return False

            # Retrieve role config to verify allowed_tools
            role = self.agent_registry.get_role(agent.role)
            if not role:
                return False

            # Let's check if tool is listed or if it's wildcard
            if resource not in role.allowed_tools and "*" not in role.allowed_tools:
                return False

        # Authority-based checks
        if action_type == "write_file":
            return agent.authority_level >= 1
        if action_type == "production_change" or action_type == "merge_branch":
            return agent.authority_level >= 3
        if action_type == "delegate":
            return agent.authority_level >= 4
        if action_type == "cross_pod_coordinate" or action_type == "request_founder_approval":
            return agent.authority_level >= 5
        if action_type == "execute_tool":
            # Already checked earlier, return True if we reached here
            return True

        # Deny-by-Default (Least-Privilege)
        return False
