"""Shell helpers for local diagnostics."""

from dataclasses import dataclass
import subprocess


@dataclass(slots=True)
class CommandResult:
    """Captured shell command result."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        """Return stdout and stderr as one string."""

        return "\n".join(part for part in [self.stdout, self.stderr] if part).strip()


def run_command(args: list[str], timeout_seconds: int = 30) -> CommandResult:
    """Run a shell command safely."""

    try:
        completed = subprocess.run(  # nosec B603
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return CommandResult(tuple(args), 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            tuple(args),
            124,
            exc.stdout or "",
            exc.stderr or "Command timed out.",
        )

    return CommandResult(
        tuple(args),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
