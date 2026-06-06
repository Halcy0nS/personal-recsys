"""Backward-compatible wrapper for the canonical demo entrypoint."""

from scripts.demo.example_usage import main


if __name__ == "__main__":
    print("Canonical entrypoint: python3 scripts/demo/example_usage.py")
    main()
