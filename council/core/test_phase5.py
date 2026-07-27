# Test suite verifying Founder Dashboard rendering and non-blocking event layouts

import pytest
from council.core.dashboard import run_dry_run_dashboard

def test_dashboard_rendering_and_layout():
    # Execute dry-run rendering
    rendered = run_dry_run_dashboard()

    # Assert headers and key blocks exist in the layout
    assert "THE COUNCIL - FOUNDER DASHBOARD" in rendered
    assert "[SYSTEM RUNTIME STATUS]" in rendered
    assert "[BUDGET STATUS]" in rendered
    assert "[ACTIVE WORKFLOW TASKS]" in rendered
    assert "[ACTIVE ESCALATIONS]" in rendered
    assert "[SYSTEM INCIDENTS & ROLLBACK LOG]" in rendered

    # Assert simulated task details and alerts were correctly captured
    assert "Draft legal contracts" in rendered
    assert "legal_builder" in rendered
    assert "3 failed verification attempts" in rendered
    assert "Container crash loop detected" in rendered
    assert "restart_worker_service" in rendered

    print("Phase 5 Dashboard rendering and dry-run check executed and passed successfully!")
