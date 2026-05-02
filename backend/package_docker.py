#!/usr/bin/env python3
"""
Package all Lambda functions using Docker for AWS compatibility.
Runs each agent's package_docker.py script.
"""

import os
import sys
import subprocess
from pathlib import Path

# Windows consoles often default to cp1252; avoid UnicodeEncodeError on prints.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run_packaging(agent_name):
    """Run packaging for a specific agent."""
    agent_dir = Path(__file__).parent / agent_name
    package_script = agent_dir / "package_docker.py"

    if not package_script.exists():
        print(f"  [FAIL] {agent_name}: Missing package_docker.py")
        return False

    print(f"\n[PACK] Packaging {agent_name.upper()} agent...")
    print(f"  Running: cd {agent_dir} && uv run package_docker.py")

    try:
        result = subprocess.run(
            ["uv", "run", "package_docker.py"], cwd=str(agent_dir), capture_output=True, text=True
        )

        if result.returncode == 0:
            # Look for the created zip file
            zip_files = list(agent_dir.glob("*.zip"))
            if zip_files:
                zip_file = zip_files[0]
                size_mb = zip_file.stat().st_size / (1024 * 1024)
                print(f"  [OK] Created: {zip_file.name} ({size_mb:.1f} MB)")
                return True
            else:
                print(f"  [WARN] No zip file found after packaging")
                return True
        else:
            print(
                f"  [FAIL] Error with {agent_name.upper()}:\nPlease note that warnings about uv environment can be ignored:\n{result.stderr}\nOutput from script is:\n{result.stdout}"
            )
            return False

    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return False


def main():
    """Package all Lambda functions."""
    print("=" * 60)
    print("PACKAGING ALL LAMBDA FUNCTIONS")
    print("=" * 60)

    agents = ["tagger", "reporter", "charter", "retirement", "planner"]
    results = {}

    for agent in agents:
        success = run_packaging(agent)
        results[agent] = success

    print("\n" + "=" * 60)
    print("PACKAGING SUMMARY")
    print("=" * 60)

    success_count = sum(1 for s in results.values() if s)
    total_count = len(results)

    for agent, success in results.items():
        status = "Success" if success else "Failed"
        print(f"{agent.ljust(12)}: {status}")

    print("\n" + "=" * 60)
    print(f"Packaged: {success_count}/{total_count}")

    if success_count == total_count:
        print("\n[OK] ALL LAMBDA FUNCTIONS PACKAGED SUCCESSFULLY!")
        print("\nNext steps:")
        print("1. Deploy infrastructure: cd terraform/6_agents && terraform apply")
        print("2. Deploy Lambda functions: cd backend && uv run deploy_all_lambdas.py")
        return 0
    else:
        print(f"\n[WARN] {total_count - success_count} agents failed to package")
        return 1


if __name__ == "__main__":
    sys.exit(main())
