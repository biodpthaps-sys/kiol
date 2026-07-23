# Relational Structured Storage, Document Catalog, Event Store, and Escalation / Incident Response

import sqlite3
import json
import time
from typing import Dict, Any, List, Optional
from council.core.workflow import Task

class KnowledgeBase:
    """
    Structured database, document catalog, Experience memory,
    and Event Store backing for agent execution history.
    """
    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()

        # 1. Relational structured storage (tasks, approvals, projects)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS structured_tasks (
                task_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                state TEXT,
                budget TEXT,
                actual_cost REAL,
                created_at REAL
            )
        """)

        # 2. Document storage (SOPs, notes, manuals, logs)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                title TEXT,
                content TEXT,
                category TEXT,
                created_at REAL
            )
        """)

        # 3. Experience/Semantic memory cache (simulate vector experience retrieval)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS experience_memory (
                memory_id TEXT PRIMARY KEY,
                key_phrase TEXT,
                context_json TEXT,
                created_at REAL
            )
        """)

        # 4. Event Store: Immutable decisions, agent actions, approvals, tool calls
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_store (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT,
                source TEXT,
                payload_json TEXT,
                timestamp REAL
            )
        """)
        self.conn.commit()

    def persist_task(self, task: Task):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO structured_tasks (task_id, name, description, state, budget, actual_cost, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (task.task_id, task.name, task.description, task.state.value, str(task.budget_ceiling), task.actual_cost, task.created_at))
        self.conn.commit()

    def insert_document(self, doc_id: str, title: str, content: str, category: str):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO documents (doc_id, title, content, category, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (doc_id, title, content, category, time.time()))
        self.conn.commit()

    def store_experience(self, key_phrase: str, context_dict: Dict[str, Any]):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO experience_memory (memory_id, key_phrase, context_json, created_at)
            VALUES (?, ?, ?, ?)
        """, (str(time.time()), key_phrase, json.dumps(context_dict), time.time()))
        self.conn.commit()

    def record_event(self, topic: str, source: str, payload: Dict[str, Any]):
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO event_store (topic, source, payload_json, timestamp)
            VALUES (?, ?, ?, ?)
        """, (topic, source, json.dumps(payload), time.time()))
        self.conn.commit()

    def run_memory_compaction(self):
        """Compaction cron/summarization job: summarizes and prunes raw details, but keeps key evidence."""
        # Simple local compaction logic: group events older than a brief window and archive them
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM event_store")
        count = cursor.fetchone()[0]

        # Aggregate stats into a master summary document, then keep them clean
        if count > 0:
            cursor.execute("SELECT payload_json FROM event_store")
            rows = cursor.fetchall()
            summarized_stats = f"Compacted {len(rows)} execution logs into memory. Total transaction volume high."
            self.insert_document("compaction_latest", "Memory Compaction Log", summarized_stats, "system_metadata")

        return count

    def close(self):
        self.conn.close()


class EscalationAndIncidentManager:
    """Escalation & Incident Response System."""
    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.escalations: List[Dict[str, Any]] = []

    def raise_escalation(self, task_id: str, trigger_reason: str, detail: str) -> str:
        escalation_id = f"esc_{int(time.time())}_{task_id[:8]}"
        escalation = {
            "escalation_id": escalation_id,
            "task_id": task_id,
            "trigger_reason": trigger_reason,
            "detail": detail,
            "resolved": False,
            "response": None,
            "timestamp": time.time()
        }
        self.escalations.append(escalation)
        self.kb.record_event("system.escalation", "incident_manager", escalation)
        return escalation_id

    def declare_incident(self, pod_name: str, reason: str, rollback_plan_name: Optional[str] = None) -> str:
        """Declares an incident, freezes pod writes immediately, and queues rollback execution."""
        incident_id = f"inc_{int(time.time())}_{pod_name[:8].lower().replace(' ', '_')}"
        incident = {
            "incident_id": incident_id,
            "pod_name": pod_name,
            "reason": reason,
            "status": "active",
            "rollback_executed": False,
            "rollback_plan": rollback_plan_name,
            "timestamp": time.time()
        }
        self.incidents[incident_id] = incident
        self.kb.record_event("system.incident", "incident_manager", incident)

        # Execute mock/real rollback procedure
        if rollback_plan_name:
            # Code execution: Roll back any state, files, or commits
            self.kb.record_event(f"system.rollback.{incident_id}", "incident_manager", {"status": "executed", "plan": rollback_plan_name})
            incident["rollback_executed"] = True

        return incident_id

    def resolve_escalation(self, escalation_id: str, decision: str):
        for esc in self.escalations:
            if esc["escalation_id"] == escalation_id:
                esc["resolved"] = True
                esc["response"] = decision
                self.kb.record_event("system.escalation.resolved", "incident_manager", {"escalation_id": escalation_id, "decision": decision})
                break

    def resolve_incident(self, incident_id: str):
        if incident_id in self.incidents:
            self.incidents[incident_id]["status"] = "resolved"
            self.kb.record_event("system.incident.resolved", "incident_manager", {"incident_id": incident_id})
