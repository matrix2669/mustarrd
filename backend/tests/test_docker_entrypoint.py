import re
import subprocess
import unittest
from pathlib import Path


ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"


def _shell_function(name: str) -> str:
    source = ENTRYPOINT.read_text()
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"Could not find shell function {name}")
    return match.group(0)


def _run_bash(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", f"set -euo pipefail\n{body}"],
        text=True,
        capture_output=True,
        check=False,
    )


class DockerEntrypointGroupTests(unittest.TestCase):
    def test_entrypoint_has_valid_shell_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(ENTRYPOINT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_gid_returns_its_real_group_name(self):
        result = _run_bash(
            f"""
{_shell_function("ensure_group")}
getent() {{
  [[ "$1" == "group" && "$2" == "107" ]] || return 2
  printf 'renderhost:x:107:\n'
}}
groupadd() {{ return 91; }}
groupmod() {{ return 92; }}
[[ "$(ensure_group render 107)" == "renderhost" ]]
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_gid_creates_and_returns_requested_group(self):
        result = _run_bash(
            f"""
{_shell_function("ensure_group")}
getent() {{ return 2; }}
groupadd() {{
  [[ "$1" == "-g" && "$2" == "108" && "$3" == "render" ]]
}}
groupmod() {{ return 92; }}
[[ "$(ensure_group render 108)" == "render" ]]
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_existing_requested_name_is_moved_to_device_gid(self):
        result = _run_bash(
            f"""
{_shell_function("ensure_group")}
getent() {{
  if [[ "$1" == "group" && "$2" == "render" ]]; then
    printf 'render:x:44:\n'
    return 0
  fi
  return 2
}}
groupadd() {{ return 91; }}
groupmod() {{
  [[ "$1" == "-g" && "$2" == "109" && "$3" == "render" ]]
}}
[[ "$(ensure_group render 109)" == "render" ]]
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
