"""Run the full archetypes pipeline: features -> assign -> yearwise."""

from __future__ import annotations

from . import run_role_features, run_assign, run_yearwise


def main() -> None:
    print("=== Phase 1: role features ===")
    run_role_features.main()
    print("\n=== Phase 3: assignment ===")
    run_assign.main()
    print("\n=== Phase 4: yearwise ===")
    run_yearwise.main()


if __name__ == "__main__":
    main()
