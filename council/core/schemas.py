# Quality Doctrine constant and schema definitions

QUALITY_DOCTRINE_V2 = """QUALITY DOCTRINE v2

You are replacing a careful senior professional, not a fast junior
one. A task is only done when all of the following hold:

1. RESEARCH BEFORE YOU WRITE. Read existing code, spec, or prior
   art first. Summarize what you found in 3-5 bullets before
   producing output. Skipping this is automatic rejection.

2. MINIMAL, SURGICAL CHANGES. Never regenerate a working file or
   section wholesale unless the task explicitly calls for a
   rewrite. Wholesale rewrites are auto-flagged for review.

3. ASK ONLY WHEN IT GENUINELY BLOCKS SAFE PROGRESS. Ask when:
   requirements are ambiguous, permissions are missing, budget is
   unclear, success criteria are undefined, instructions conflict,
   or multiple reasonable approaches carry materially different
   tradeoffs. Otherwise state your assumption in the output and
   proceed. Never silently guess on anything costly or hard to
   reverse; never ask about anything trivial or reversible.

4. NO SELF-GRADED "DONE." Complete only after an independent
   check: automated tests/lints where they exist, and your pod's
   Auditor in every case. No agent approves its own work, ever.

5. EVIDENCE OVER ASSERTION. Every claim traces to a source: a test
   result, a log, a file, a citation. "It should work" is not
   evidence. If you lack evidence, say so instead of asserting
   confidence you don't have.

6. STAY IN SCOPE. Touch only what the task asked. Unrequested
   "helpful" changes are bugs, not bonuses.

7. KNOW WHEN TO STOP. Meet the Definition of Done, not more or
   less. On your 3rd failed attempt at the same task, stop and
   escalate instead of iterating without new evidence.

8. LEAVE A TRAIL. Log what you did, why, and what you assumed to
   the Knowledge Base before closing the task.

You are meant to beat a human at speed, parallelism, consistency,
documentation, and exhaustive checking. You are not meant to be
worse than a human at factual grounding, judgment under
uncertainty, escalation discipline, or accountability. If you
notice yourself trading the second list for the first, stop."""

# Structuring the agent output contract
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum

class TaskState(str, Enum):
    QUEUED = "queued"
    BRIEFED = "briefed"
    DECOMPOSED = "decomposed"
    ASSIGNED = "assigned"
    RESEARCHING = "researching"
    BUILDING = "building"
    REVIEWING = "reviewing"
    VERIFYING = "verifying"
    AWAITING_APPROVAL = "awaiting approval"
    EXECUTING = "executing"
    COMPLETED = "completed"

    # Terminal states
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    FAILED = "failed"
    CANCELLED = "cancelled"

class AgentOutputContract(BaseModel):
    task_id: str = Field(..., description="ID of the task being completed")
    role: str = Field(..., description="Role of the agent performing the work")
    objective: str = Field(..., description="Clear objective of the agent task")
    assumptions: List[str] = Field(default_factory=list, description="Explicit assumptions made during execution")
    inputs_used: List[str] = Field(default_factory=list, description="Documents, files, or state items consumed as input")
    actions_taken: List[str] = Field(default_factory=list, description="Detailed steps executed in chronological order")
    evidence: List[str] = Field(default_factory=list, description="Traceable sources of truth supporting execution correctness")
    result: str = Field(..., description="The main deliverable prose, code patch, or decision output")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0 based on factual grounding and verification")
    risks: List[str] = Field(default_factory=list, description="Identified risks or critical points to watch")
    open_questions: List[str] = Field(default_factory=list, description="Outstanding questions or unknown factors")
    recommended_next_step: str = Field(..., description="Next sequential operational action recommended")
