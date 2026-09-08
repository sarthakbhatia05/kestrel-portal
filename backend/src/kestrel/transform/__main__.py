import argparse
import sys

from kestrel.config import get_settings
from kestrel.transform.runner import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kestrel.transform")
    parser.add_argument("command", choices=["build"])
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.command == "build":
        print(f"Source:  {settings.source_db_path}")
        print(f"Curated: {settings.curated_db_path}")
        result = build(settings.source_db_path, settings.curated_db_path)
        print(f"\nBuilt in {result.duration_seconds:.1f}s (run {result.run_id})")
        for table, count in result.table_counts.items():
            print(f"  {table:<20} {count:>9,}")
        print("\nQuality ledger by rule:")
        for rule, count in sorted(result.ledger_counts.items()):
            print(f"  {rule:<20} {count:>9,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
