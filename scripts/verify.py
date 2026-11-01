import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    "tests/portfolio", "tests/core/test_observability.py", "tests/core/test_confidence.py",
    "tests/test_context_assembly.py", "tests/test_summarizer.py", "tests/test_tools_mock.py",
    "tests/tools/test_order_ownership.py", "tests/test_tool_ticket.py", "tests/tools/test_registry.py",
    "tests/tools/test_engine.py", "tests/tools/test_mcp_client.py",
]


def main() -> int:
    directory = ROOT / ".cache" / "pytest"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("run-" + uuid4().hex)
    command = [sys.executable, "-m", "pytest", *TESTS, "-q", "--tb=short",
               "--basetemp", str(target), *sys.argv[1:]]
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
