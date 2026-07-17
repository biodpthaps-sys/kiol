import os
import subprocess

class SandboxManager:
    def __init__(self, workspace_path="workspace/nodebb_sandbox"):
        self.workspace_path = workspace_path

    def run_command(self, cmd, timeout=300):
        """
        Runs a command inside the workspace directory.
        """
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workspace_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return res.returncode, res.stdout, res.stderr
        except subprocess.TimeoutExpired as e:
            return -1, "", f"Timeout expired: {str(e)}"

    def run_tests(self):
        """
        Runs the target test files.
        """
        # Run Mocha tests for database keys and user emails
        code1, out1, err1 = self.run_command("npx mocha test/database/keys.js")
        code2, out2, err2 = self.run_command("npx mocha test/user/emails.js")

        passed = True
        log = ""

        if code1 != 0:
            passed = False
            log += f"Database keys tests failed:\n{out1}\n{err1}\n"
        else:
            log += "Database keys tests passed successfully.\n"

        if code2 != 0:
            passed = False
            log += f"User emails tests failed:\n{out2}\n{err2}\n"
        else:
            log += "User emails tests passed successfully.\n"

        return passed, log

    def get_diff(self, base_commit):
        """
        Returns the git diff compared to the base commit.
        """
        code, out, err = self.run_command(f"git diff {base_commit}")
        return out
