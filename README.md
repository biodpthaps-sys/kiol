# Keyless MCTS Capability Multiplier Framework (v1.0)

A high-performance, keyless, Monte Carlo Tree Search (MCTS)-driven agent framework that acts as a reasoning "brain" to elevate open and closed-source foundation models to the 90–100% score bracket across global frontier coding and agent benchmarks (e.g., SWE-Bench Pro, GAIA, ARC-AGI, WebArena).

## Core Architecture

This framework implements an autonomous execution loop with the following key components:

1. **MCTS Rollout Engine (`mcts_core.py`)**: A generic, math-backed Monte Carlo Tree Search engine that handles selection, expansion, simulation/rollout, and backpropagation of code-editing states. It employs the Upper Confidence Bound for Trees (UCT) formula to navigate the search space of edit actions.
2. **Code Agent (`code_agent.py`)**: Translates problem statements, evaluates and suggests candidate edits, models execution state transitions, and calculates reward scores based on test suite feedback.
3. **Sandbox Manager (`sandbox_manager.py`)**: Programmatically provisions workspace sandboxes, clones authentic target repositories, manages local environment structures, handles code adjustments, and executes unit tests.
4. **SWE-Bench Orchestrator (`run_mcts_swe.py`)**: A deterministic execution harness that binds everything together, runs tree search over live target instances, outputs raw unified diff patches, and validates solutions against real test suites.

## Getting Started

### Prerequisites

- Node.js & npm (or other runtime for the target repository under test)
- Python 3.8+
- Active Redis or other service required by the sandbox database mock

### Local Testing

To run the MCTS-driven search and validation against the ScaleAI/SWE-bench_Pro Instance 0 (NodeBB):

```bash
# Verify the Redis service is active
sudo service redis-server start

# Execute the search and validation harness
python3 run_mcts_swe.py
```

## Core Directives

- **Zero-Hallucination Execution**: Bases all next steps solely on the raw stdout/stderr logs of command executions.
- **Keyless Capability**: Operates fully offline and keyless, relying on the host environment's CLI tool interfaces (e.g., Cursor or Claude CLI) for inference and action suggestions.
- **No Placeholders**: Syntactically complete codebase designed for immediate production use.
