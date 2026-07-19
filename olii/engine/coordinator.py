import asyncio
import logging
from enum import Enum, auto
from typing import Dict, Any, List

# Import components from adjacent engine modules
from olii.engine.interceptor import StreamInterceptor, DeterministicComplianceError
from olii.engine.scaffolder import detect_environment, generate_harness, execute_isolated_harness

# Configure logger
logger = logging.getLogger("olii.engine.coordinator")
logging.basicConfig(level=logging.INFO)


class OliiState(Enum):
    """
    Component A: The Engine Coordinator State Machine Enums
    """
    INGESTION = auto()
    INJECT_PATCH = auto()
    VERIFY_HARNESS = auto()
    PURGE_RELEASE = auto()


class OliiCoordinator:
    """
    Component A: Central orchestration class OliiCoordinator
    Handles global runtime flags, workspace path bindings, and active state transitions.
    """
    def __init__(self, repo_path: str, api_client: Any):
        self.repo_path = repo_path
        self.api_client = api_client
        self.state = OliiState.INGESTION
        self.interceptor = StreamInterceptor()
        self.memory: List[Dict[str, Any]] = []

    def set_state(self, new_state: OliiState) -> None:
        """Logs and transitions coordinator state."""
        logger.info(f"[COORDINATOR] State transition: {self.state.name} -> {new_state.name}")
        self.state = new_state

    async def run_lifecycle(self, instance_data: dict) -> bool:
        """
        Component B & C: The Integrated Lifecycle Orchestrator
        Orchestrates the full multi-stage execution pipeline with hard-fault trapping,
        automatic workspace recovery, and conversation memory pruning on compliance failures.
        """
        prompt = instance_data.get("prompt", "")
        system_instruction = instance_data.get("system_instruction", "You are an expert coder. Write a patch to resolve the bug.")
        targets = instance_data.get("targets", [])
        context_delta = instance_data.get("context_delta", "")

        # --- Stage 1: INGESTION ---
        self.set_state(OliiState.INGESTION)
        logger.info("[COORDINATOR] Analyzing repository environment and config files...")
        env_info = detect_environment(self.repo_path)
        logger.info(f"[COORDINATOR] Environment discovery complete. Stack identified: {env_info['stack']}")

        # --- Stage 2: INJECT_PATCH ---
        self.set_state(OliiState.INJECT_PATCH)
        logger.info("[COORDINATOR] Triggering streaming patch generation with interceptor enforcement...")

        try:
            # Append prompt to conversation memory
            self.memory.append({"role": "user", "content": prompt})

            # Execute interceptor monitored completion
            patch_chunks = []
            async for chunk in self.interceptor.stream_and_intercept(
                self.api_client,
                prompt,
                system_instruction
            ):
                patch_chunks.append(chunk)

            patch_content = "".join(patch_chunks)
            self.memory.append({"role": "assistant", "content": patch_content})
            logger.info("[COORDINATOR] Patch generated and saved successfully to conversation memory.")

            # --- Stage 3: VERIFY_HARNESS ---
            self.set_state(OliiState.VERIFY_HARNESS)
            logger.info("[COORDINATOR] Scaffolding standalone test harness script...")
            script_name = await generate_harness(self.repo_path, targets, context_delta)

            logger.info("[COORDINATOR] Executing detached async validation harness...")
            exec_results = await execute_isolated_harness(self.repo_path, script_name)

            if exec_results["exit_code"] != 0:
                logger.error(f"[COORDINATOR] Validation harness failed with exit code: {exec_results['exit_code']}")
                logger.error(f"stderr: {exec_results['stderr']}")
                raise DeterministicComplianceError("Harness verification failed.")

            logger.info("[COORDINATOR] Detached async validation harness passed with exit code 0.")

            # --- Stage 4: PURGE_RELEASE ---
            self.set_state(OliiState.PURGE_RELEASE)
            logger.info("[COORDINATOR] Dropping temporary test artifacts...")
            import os
            script_path = os.path.join(self.repo_path, script_name)
            if os.path.exists(script_path):
                os.remove(script_path)

            logger.info("[COORDINATOR] Finalizing and staging production changes.")
            # Standard return of successful lifecycle execution
            return True

        except (DeterministicComplianceError, Exception) as e:
            logger.warning(f"[COORDINATOR] Failure encountered: {str(e)}. Initiating Hard-Fault Trapping...")

            # Workspace Recovery (Git hard reset and clean)
            self.interceptor.recover_workspace()

            # Conversation memory pruning: erase the failed turn (last user and assistant messages)
            if len(self.memory) >= 2:
                logger.info("[COORDINATOR] Pruning internal conversation memory of the failed turn...")
                self.memory = self.memory[:-2]

            # Re-drive Stage 2 at temperature=0.0
            logger.info("[COORDINATOR] Initiating re-drive loop with forced temperature=0.0...")
            self.set_state(OliiState.INJECT_PATCH)

            try:
                # Add re-drive request to memory
                redrive_prompt = (
                    f"{prompt}\n"
                    "[SYSTEM ERROR]: Output formatting violation or verification failure detected. "
                    "You are restricted to raw terminal blocks. Do not summarize."
                )
                self.memory.append({"role": "user", "content": redrive_prompt})

                # Force temperature=0.0 option
                redrive_options = {"temperature": 0.0}

                patch_chunks = []
                async for chunk in self.interceptor.stream_and_intercept(
                    self.api_client,
                    redrive_prompt,
                    system_instruction,
                    redrive_options
                ):
                    patch_chunks.append(chunk)

                patch_content = "".join(patch_chunks)
                self.memory.append({"role": "assistant", "content": patch_content})

                # Re-verify redriven patch
                self.set_state(OliiState.VERIFY_HARNESS)
                script_name = await generate_harness(self.repo_path, targets, context_delta)
                exec_results = await execute_isolated_harness(self.repo_path, script_name)

                if exec_results["exit_code"] == 0:
                    self.set_state(OliiState.PURGE_RELEASE)
                    import os
                    script_path = os.path.join(self.repo_path, script_name)
                    if os.path.exists(script_path):
                        os.remove(script_path)
                    logger.info("[COORDINATOR] Re-drive pipeline verification succeeded!")
                    return True
                else:
                    logger.error("[COORDINATOR] Re-drive pipeline failed harness verification again.")
                    return False

            except Exception as redrive_err:
                logger.error(f"[COORDINATOR] Critical pipeline crash during re-drive loop: {str(redrive_err)}")
                return False
