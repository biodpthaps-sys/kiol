import asyncio
import logging
import re
import subprocess
from typing import AsyncGenerator, List, Any, Dict

# Configure logger
logger = logging.getLogger("olii.engine.interceptor")
logging.basicConfig(level=logging.INFO)

class DeterministicComplianceError(Exception):
    """Raised when a banned phrase, emoji, or non-code summary is detected in the stream buffer."""
    pass


class StreamInterceptor:
    """
    Advanced multi-agent stream interceptor that streams LLM completions,
    maintains a sliding text buffer, and aggressively enforces strict output formatting.
    """
    def __init__(self):
        # Banned phrases and patterns matrix (The Ban List)
        self.banned_phrases = [
            "ready for review",
            "all steps completed",
            "here is the plan",
            "i have modified"
        ]
        # Regex to detect any emojis (e.g., 🎉, 🚀, ✅)
        self.emoji_pattern = re.compile(
            r"[\U00010000-\U0010ffff]|\u2600-\u27BF|[\u2000-\u3300]"
        )
        # Regex to detect non-code markdown structural summaries (milestone lists, checkmarks)
        self.markdown_summary_pattern = re.compile(
            r"(-\s*\[\s*[xX ]\s*\])|(^\s*[\*\+-]\s+\w+)|(^\s*\d+\.\s+\w+)",
            re.MULTILINE
        )

    def contains_banned_content(self, buffer: str) -> bool:
        """Evaluates the sliding window buffer against the ban list matrix."""
        buffer_lower = buffer.lower()

        # Check explicit banned phrases
        for phrase in self.banned_phrases:
            if phrase in buffer_lower:
                logger.error(f"[INTERCEPTOR] Banned phrase detected: '{phrase}'")
                return True

        # Check for emojis
        if self.emoji_pattern.search(buffer):
            logger.error("[INTERCEPTOR] Banned emoji pattern detected in buffer.")
            return True

        # Check for non-code markdown summaries/checkmarks
        if self.markdown_summary_pattern.search(buffer):
            logger.error("[INTERCEPTOR] Non-code markdown list or checkmark detected in buffer.")
            return True

        return False

    async def stream_and_intercept(
        self,
        api_client: Any,
        prompt: str,
        system_instruction: str,
        options: Dict[str, Any] = None
    ) -> AsyncGenerator[str, None]:
        """
        Streams completions from the api_client and monitors a moving text buffer
        of the last 64 characters to enforce deterministic compliance.
        """
        sliding_window = ""
        options = options or {}

        # Stream completions from api_client, forwarding options (like temperature)
        async for chunk in api_client.stream(
            prompt=prompt,
            system_instruction=system_instruction,
            options=options
        ):
            if not chunk:
                continue

            sliding_window += chunk
            # Keep sliding window to maximum of 64 characters
            if len(sliding_window) > 64:
                sliding_window = sliding_window[-64:]

            # Evaluate the buffer against the ban list
            if self.contains_banned_content(sliding_window):
                raise DeterministicComplianceError("Output formatting violation detected.")

            yield chunk

    def recover_workspace(self) -> None:
        """
        Natively executes shell recovery commands to guarantee zero workspace drift
        by resetting and cleaning the tracked git directory.
        """
        try:
            logger.info("[RECOVERY] Executing Native Git Hard Reset & Clean...")
            subprocess.run(["git", "reset", "--hard", "HEAD"], check=True, capture_output=True)
            subprocess.run(["git", "clean", "-fd"], check=True, capture_output=True)
            logger.info("[RECOVERY] Workspace successfully reset to clean HEAD.")
        except subprocess.CalledProcessError as e:
            logger.error(f"[RECOVERY] Critical error during git workspace cleanup: {e.stderr.decode()}")
            raise e

    async def run_with_redrive(
        self,
        api_client: Any,
        prompt: str,
        system_instruction: str,
        options: Dict[str, Any] = None
    ) -> List[str]:
        """
        Orchestrates streaming with automated recovery and re-drive capabilities.
        If a compliance error occurs, resets the workspace and automatically re-drives
        the request exactly once with a system override and temperature forced to 0.0.
        """
        options = options or {}
        output_chunks = []
        try:
            async for chunk in self.stream_and_intercept(
                api_client,
                prompt,
                system_instruction,
                options
            ):
                output_chunks.append(chunk)
            return output_chunks

        except DeterministicComplianceError:
            logger.warning("[INTERCEPTOR] Compliance error caught. Initiating Workspace Recovery...")
            self.recover_workspace()

            logger.info("[INTERCEPTOR] Re-driving LLM request with temperature=0.0 and system override...")
            # Unyielding system override append
            override_instruction = (
                f"{system_instruction}\n"
                "[SYSTEM ERROR]: Output formatting violation detected. "
                "You are restricted to raw terminal blocks. Do not summarize."
            )

            # Clone options and force temperature=0.0
            redrive_options = dict(options)
            redrive_options["temperature"] = 0.0

            # Re-drive exactly once with temperature=0.0
            re_driven_chunks = []
            async for chunk in self.stream_and_intercept(
                api_client,
                prompt,
                override_instruction,
                redrive_options
            ):
                re_driven_chunks.append(chunk)

            return re_driven_chunks
