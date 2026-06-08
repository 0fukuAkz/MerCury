---
goal: Unpin Python 3.12 version restrictions to support a broader range of Python environments
version: 1.0
date_created: 2026-05-30
owner: MerCury Team
status: 'Planned'
tags: [upgrade, chore, architecture, migration]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This implementation plan outlines the steps necessary to safely unpin Python 3.12 restrictions within the MerCury codebase. Currently, dependency constraints under [pyproject.toml](pyproject.toml) and several build/run configuration files enforce Python 3.12 exclusively. Relaxing these bounds simplifies integration in different development environments, supports production installations on older/newer runtime hosts, and allows seamless adoption of Python 3.13 without diagnostic errors.

## 1. Requirements & Constraints

Below is the complete set of requirements and architectural constraints establishing how the version unpinning must be structured:

- **REQ-001**: Upper-bound version relaxation. Modify the package definition to support Python 3.13 (and optionally future releases) by removing strictly bounded `<3.13` clauses.
- **REQ-002**: Lower-bound selection. Define whether the minimum supported version remains 3.12, or is expanded downwards.
  - **Option A (Recommended & Clean)**: Maintain Python 3.12 as the floor (`>=3.12`). This preserves native usage of standard library features (such as `from datetime import UTC` and optimized f-strings) without requiring shims or backwards compatibility patches.
  - **Option B (Broad Compatibility)**: Drop the floor to Python 3.10 or 3.11 (`>=3.10` or `>=3.11`). This triggers the need for fallback wrappers/polyfills to support `datetime.UTC` on older runtimes.
- **CON-001**: Docker and runtime consistency. Development, testing, and devcontainer environments should continue to use a vetted reference version (Python 3.12) to ensure predictable builds and prevent CI noise.
- **CON-002**: CI Test Coverage. The continuous integration pipeline must continue to run its comprehensive suite under Python 3.12, with optional matrix expansion to execute tests across Python 3.13.

## 2. Implementation Steps

### Phase 1: Package Definitions & Configurations

- GOAL-001: Modify core configuration files to expand the supported Python version range.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Update `requires-python` in [pyproject.toml](pyproject.toml) from `">=3.12,<3.13"` to `>=3.12` (or `>=3.12,<3.14`), and add the Programming Language classifier for Python 3.13. | | |
| TASK-002 | Update developer environment guidance and shell configuration in [.envrc](.envrc) to show setup instructions for compatible version ranges instead of a pinned version. | | |
| TASK-003 | Update PowerShell environment script [activate.ps1](activate.ps1) instructions to reference generic Python 3 commands instead of hardcoded 3.12 launcher calls. | | |

### Phase 2: CI/CD Pipeline & Development Environments

- GOAL-002: Ensure CI environments and developer setups are aligned with version expansion.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-004 | Update the testing matrix in [.github/workflows/ci.yml](.github/workflows/ci.yml) to run tests against both Python 3.12 and 3.13. | | |
| TASK-005 | Update security and build jobs in [.github/workflows/ci.yml](.github/workflows/ci.yml) to use standard/latest Python setups rather than hardcoded 3.12 pins. | | |
| TASK-006 | Update reference documentation and metadata files like [README.md](README.md) and [CLAUDE.md](CLAUDE.md) to explain the relaxed compatibility requirements. | | |

## 3. Alternatives

- **ALT-001**: **Downward Compatibility to Python 3.10+**.
  - *Details*: Relax the minimum required Python standard to `>=3.10` or `>=3.11`.
  - *Rationale for Denial*: This is not selected as the primary path because the codebase heavily imports `datetime.UTC`. If we drop below Python 3.11, pre-import validations or a compatibility shim would be required in a core module (e.g. replacing `from datetime import UTC` with a fallback `try/except` importing `timezone.utc`). Since Python 3.12 is widely deployed, maintaining `>=3.12` as the modern standard is the cleanest architectural style.
- **ALT-002**: **Strict pinning for Python 3.13 (`>=3.12,<3.14`)**.
  - *Details*: Place an explicit cap at Python 3.14 to prevent future unexpected standard library changes from breaking automated tasks.
  - *Rationale for Acceptance*: This is kept as a viable, safe intermediate step in [pyproject.toml](pyproject.toml) to enforce `requires-python = ">=3.12,<3.14"`.

## 4. Dependencies

- **DEP-001**: **Local dev tools**. Editors, linters, and checkers (such as `ruff`, `mypy`, and `bandit`) must run successfully in any environment with relaxed versions.
- **DEP-002**: **C-extensions & Wheels**. Dependent packages must verify compile compatibility with Python 3.13 (e.g. `eventlet`, `aiosmtplib`, `greenlet`).

## 5. Files

- **FILE-001**: [pyproject.toml](pyproject.toml) — Relaxation of required Python bounds and version metadata classifiers.
- **FILE-002**: [.github/workflows/ci.yml](.github/workflows/ci.yml) — Alignment of test execution strategies and matrix expansion.
- **FILE-003**: [.envrc](.envrc) — Standard shell messaging parameters.
- **FILE-004**: [activate.ps1](activate.ps1) — Local tooling configurations.
- **FILE-005**: [README.md](README.md) — Public environment prerequisites.
- **FILE-006**: [CLAUDE.md](CLAUDE.md) — Coding assistant guides.

## 6. Testing

- **TEST-001**: **Matrix Integration Test**. Execute the full suite under active environments running both standard Python 3.12 and Python 3.13.
- **TEST-002**: **Wheel Smoke Verification**. Verify build cycle via `make test-wheel` to confirm package creation succeeds with the expanded specification.

## 7. Risks & Assumptions

- **RISK-001**: Minor library or binary incompatibilities on Python 3.13. Dependencies like `eventlet` have historically relied on platform-specific C extensions that might surface issues during initial compiles on new major interpreter versions.
- **ASSUMPTION-001**: The build system and package installers (e.g. `pip`, `build`, `setuptools`) are updated to support runtime resolution under Python 3.13.

## 8. Related Specifications / Further Reading

- [PEP 695 – Type Parameter Syntax](https://peps.python.org/pep-0695/)
- [PEP 702 – Marking Deprecations Using Type Hints](https://peps.python.org/pep-0702/)
