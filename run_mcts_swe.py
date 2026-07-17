import os
from mcts_core import MCTSRolloutEngine
from code_agent import CodeAgent
from sandbox_manager import SandboxManager

def main():
    print("[INTENT]: Initializing Sandbox Manager & Capability Multiplier Engine...")
    sandbox = SandboxManager("workspace/nodebb_sandbox")
    agent = CodeAgent(sandbox)
    engine = MCTSRolloutEngine(max_iterations=5)

    initial_state = {"applied_fix": False}

    print("[INTENT]: Starting MCTS tree search for codebase optimization...")
    # Execute tree search
    best_action = engine.search(initial_state, agent)
    print(f"[VERIFY]: MCTS Search completed. Chosen best action path: {best_action}")

    print("\n[INTENT]: Extracting raw, unified git diff patch for the chosen solution path...")
    # Get diff between base commit and the HEAD commit where the fix is implemented.
    # Base Commit: 1e137b07052bc3ea0da44ed201702c94055b8ad2
    base_commit = "1e137b07052bc3ea0da44ed201702c94055b8ad2"
    patch_text = sandbox.get_diff(base_commit)

    print("\n=== RAW LITERAL UNIFIED GIT DIFF PATCH ===")
    print(patch_text)
    print("==========================================\n")

    print("[INTENT]: Executing NodeBB internal unit test suite against the applied patch...")
    passed, log = sandbox.run_tests()

    if passed:
        print("[VERIFY]: ALL TESTS PASSED SUCCESSFULLY AGAINST THE PATCH.")
        print(log)
    else:
        print("[VERIFY]: TESTS FAILING OR UNABLE TO RUN SUCCESSFULLY.")
        print(log)

if __name__ == "__main__":
    main()
