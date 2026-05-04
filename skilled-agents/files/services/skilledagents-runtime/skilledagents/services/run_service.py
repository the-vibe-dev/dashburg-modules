from __future__ import annotations

import os
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from skilledagents.services.agent_manager import AgentManager
from skilledagents.services.log_service import LogService


class RunService:
    def __init__(self, manager: AgentManager, log_service: LogService) -> None:
        self.manager = manager
        self.log_service = log_service
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def _default_command(self, agent: dict) -> list[str]:
        workspace = Path(agent["workspace_path"])
        candidate = workspace / "run.sh"
        if candidate.exists():
            return ["bash", str(candidate)]
        return ["bash", "-lc", "echo 'agent run placeholder'; sleep 1"]

    def start(self, agent: dict, command: str | None = None, args: list[str] | None = None) -> tuple[str, int]:
        args = args or []
        disallowed = set((agent.get("specialization_metadata") or {}).get("disallowed_capabilities", []))
        if command and agent.get("specialization_mode") == "strict" and "shell_exec" in disallowed:
            raise ValueError("custom command execution is disabled by template in strict mode")
        run_id = self.manager.create_run(agent["id"], command)

        if command:
            cmd = [command, *args]
        else:
            cmd = self._default_command(agent)

        env = os.environ.copy()
        env.update(agent.get("env_config", {}))
        proc = subprocess.Popen(
            cmd,
            cwd=agent["workspace_path"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with self._lock:
            self._processes[agent["id"]] = proc

        self.manager.mark_run_started(run_id, proc.pid)
        self.manager.set_status(
            agent["id"],
            "running",
            "run started",
            active_run_id=run_id,
            active_pid=proc.pid,
            last_run_at=datetime.now(timezone.utc).isoformat(),
            metadata={"command": cmd},
        )
        self.log_service.append(agent["id"], run_id, "info", f"run started pid={proc.pid} cmd={' '.join(cmd)}")

        threading.Thread(target=self._collect_output, args=(agent["id"], run_id, proc), daemon=True).start()
        return run_id, proc.pid

    def _collect_output(self, agent_id: str, run_id: str, proc: subprocess.Popen) -> None:
        output = ""
        if proc.stdout is not None:
            for line in proc.stdout:
                output += line
                if len(output) > 1200:
                    self.log_service.append(agent_id, run_id, "stdout", output[-1200:])
                    output = ""
        code = proc.wait()
        if output:
            self.log_service.append(agent_id, run_id, "stdout", output)

        if code == 0:
            self.manager.set_status(
                agent_id,
                "idle",
                "run completed",
                active_run_id=None,
                active_pid=None,
                last_error=None,
            )
            self.log_service.append(agent_id, run_id, "info", f"run completed exit_code={code}")
            self.manager.mark_run_finished(run_id, code, None)
        else:
            err = f"run failed with exit code {code}"
            self.manager.set_status(
                agent_id,
                "error",
                "run failed",
                active_run_id=None,
                active_pid=None,
                last_error=err,
            )
            self.log_service.append(agent_id, run_id, "error", err)
            self.manager.mark_run_finished(run_id, code, err)

        with self._lock:
            self._processes.pop(agent_id, None)

    def stop(self, agent: dict) -> bool:
        with self._lock:
            proc = self._processes.get(agent["id"])
        if proc is None:
            return False

        try:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        finally:
            with self._lock:
                self._processes.pop(agent["id"], None)

        self.manager.set_status(agent["id"], "stopped", "stop requested", active_pid=None, active_run_id=None)
        self.log_service.append(agent["id"], None, "warn", "process stopped by API request")
        return True
