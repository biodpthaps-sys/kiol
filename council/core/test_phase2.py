# Test suite validating the persistent database, memory compaction, and escalation/incident handling.

import pytest
from council.core.workflow import Task
from council.core.knowledge import KnowledgeBase, EscalationAndIncidentManager

def test_knowledge_base_crud_and_compaction():
    kb = KnowledgeBase()

    # 1. Test Relational Structured Storage
    task = Task(name="Scrape web", budget_ceiling=1.5)
    kb.persist_task(task)

    # Verify task database row using kb.conn directly
    cursor = kb.conn.cursor()
    cursor.execute("SELECT name, budget FROM structured_tasks WHERE task_id=?", (task.task_id,))
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "Scrape web"
    assert row[1] == "1.5"

    # 2. Test Document Storage
    kb.insert_document("doc1", "SOP Standard Procedures", "Standard checklist for backend builder.", "SOP")

    cursor = kb.conn.cursor()
    cursor.execute("SELECT content FROM documents WHERE doc_id='doc1'")
    assert cursor.fetchone()[0] == "Standard checklist for backend builder."

    # 3. Test Event Store and Compaction
    kb.record_event("task.start", "test_builder", {"info": "starting task"})
    kb.record_event("task.complete", "test_builder", {"info": "completed"})

    count_before = kb.run_memory_compaction()
    assert count_before == 2

    # Check that compaction output summary is recorded
    cursor = kb.conn.cursor()
    cursor.execute("SELECT title, content FROM documents WHERE doc_id='compaction_latest'")
    comp_row = cursor.fetchone()
    assert comp_row is not None
    assert comp_row[0] == "Memory Compaction Log"
    assert "Compacted 2" in comp_row[1]


def test_escalation_and_incidents():
    kb = KnowledgeBase()
    manager = EscalationAndIncidentManager(kb)

    # Raise escalation
    esc_id = manager.raise_escalation("task_abc", "budget_exceeded", "Used $5.10 out of $5.00 limit.")
    assert esc_id.startswith("esc_")

    # Declare incident with rollback
    inc_id = manager.declare_incident("Backend Engineering", "Unwanted changes written to critical file", "rollback_git_reset")
    assert inc_id.startswith("inc_")
    assert manager.incidents[inc_id]["status"] == "active"
    assert manager.incidents[inc_id]["rollback_executed"] is True

    # Resolve
    manager.resolve_escalation(esc_id, "Increase budget by $1.00 and resume.")
    manager.resolve_incident(inc_id)

    assert manager.escalations[0]["resolved"] is True
    assert manager.escalations[0]["response"] == "Increase budget by $1.00 and resume."
    assert manager.incidents[inc_id]["status"] == "resolved"
