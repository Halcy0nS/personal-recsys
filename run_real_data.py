"""Backward-compatible wrapper for the canonical demo entrypoint."""

from scripts.demo.run_real_data import main


if __name__ == "__main__":
    print("Canonical entrypoint: python3 scripts/demo/run_real_data.py")
    main()
