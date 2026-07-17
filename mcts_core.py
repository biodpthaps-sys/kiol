import math
import random

class MCTSNode:
    def __init__(self, state, parent=None, action=None):
        self.state = state  # The current state of code/edits
        self.parent = parent
        self.action = action  # The edit or action that led to this state
        self.children = []
        self.visits = 0
        self.value = 0.0

    def is_fully_expanded(self, possible_actions):
        return len(self.children) >= len(possible_actions)

    def best_child(self, exploration_constant=1.414):
        best_score = -float('inf')
        best_children = []
        for child in self.children:
            if child.visits == 0:
                score = float('inf')
            else:
                # UCT formula
                exploitation = child.value / child.visits
                exploration = exploration_constant * math.sqrt(math.log(self.visits) / child.visits)
                score = exploitation + exploration

            if score > best_score:
                best_score = score
                best_children = [child]
            elif score == best_score:
                best_children.append(child)
        return random.choice(best_children) if best_children else None


class MCTSRolloutEngine:
    def __init__(self, exploration_constant=1.414, max_iterations=10):
        self.exploration_constant = exploration_constant
        self.max_iterations = max_iterations

    def search(self, initial_state, agent):
        """
        Runs the Monte Carlo Tree Search.
        initial_state: The starting state of the workspace.
        agent: The CodeAgent that handles transitions, evaluations, and action generation.
        """
        root = MCTSNode(initial_state)

        for i in range(self.max_iterations):
            print(f"[MCTS] Starting iteration {i+1}/{self.max_iterations}")
            node = root

            # 1. Selection
            possible_actions = agent.get_possible_actions(node.state)
            while node.children and node.is_fully_expanded(possible_actions):
                node = node.best_child(self.exploration_constant)
                possible_actions = agent.get_possible_actions(node.state)

            # 2. Expansion
            if not node.is_fully_expanded(possible_actions) and possible_actions:
                untried_actions = [a for a in possible_actions if a not in [c.action for c in node.children]]
                if untried_actions:
                    action = random.choice(untried_actions)
                    next_state = agent.apply_action(node.state, action)
                    new_node = MCTSNode(next_state, parent=node, action=action)
                    node.children.append(new_node)
                    node = new_node

            # 3. Simulation / Rollout
            # Rollout policy: execute actions until a terminal state or max rollout depth
            rollout_state = node.state
            depth = 0
            while not agent.is_terminal(rollout_state) and depth < 3:
                actions = agent.get_possible_actions(rollout_state)
                if not actions:
                    break
                act = random.choice(actions)
                rollout_state = agent.apply_action(rollout_state, act)
                depth += 1

            # Evaluate state
            score = agent.evaluate(rollout_state)
            print(f"[MCTS] Iteration {i+1} Rollout Evaluation Score: {score}")

            # 4. Backpropagation
            curr = node
            while curr is not None:
                curr.visits += 1
                curr.value += score
                curr = curr.parent

        # Return the best action from root
        best = root.best_child(exploration_constant=0.0)
        return best.action if best else None
