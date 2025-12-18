#!/usr/bin/env python
"""Test runner script with detailed reporting."""

import subprocess
import sys
from pathlib import Path


def run_command(cmd: list[str], description: str) -> bool:
    """Run command and report results."""
    print(f"\n{'=' * 60}")
    print(f"  {description}")
    print(f"{'=' * 60}\n")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"\n✅ {description} - PASSED")
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n❌ {description} - FAILED")
        return False


def main():
    """Run all tests and quality checks."""
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root / "src"))
    
    print("🚀 Unified Sender - Test Suite")
    print("=" * 60)
    
    results = {}
    
    # 1. Code formatting check
    results['format'] = run_command(
        ['ruff', 'format', '--check', 'src/', 'tests/'],
        "Code Formatting (Ruff)"
    )
    
    # 2. Linting
    results['lint'] = run_command(
        ['ruff', 'check', 'src/', 'tests/'],
        "Linting (Ruff)"
    )
    
    # 3. Type checking
    results['types'] = run_command(
        ['mypy', 'src/', '--ignore-missing-imports'],
        "Type Checking (MyPy)"
    )
    
    # 4. Unit tests
    results['tests'] = run_command(
        ['pytest', '-v', '--cov=src/unified_sender', '--cov-report=term-missing'],
        "Unit Tests (Pytest)"
    )
    
    # 5. Security scan
    results['security'] = run_command(
        ['bandit', '-r', 'src/', '-f', 'screen'],
        "Security Scan (Bandit)"
    )
    
    # Print summary
    print("\n" + "=" * 60)
    print("  TEST SUMMARY")
    print("=" * 60)
    
    for check, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}  {check.upper()}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nTotal: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All checks passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} check(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())

