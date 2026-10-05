"""Print a composed walkthrough bundle or check/regenerate its compatibility view."""

import argparse

from nuzlocke.knowledge.walkthrough import compose, skill_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sections", nargs="*", default=["all"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-reference", action="store_true")
    args = parser.parse_args()
    if args.check or args.write_reference:
        text = compose("all") + "\n"
        path = skill_dir() / "reference.md"
        if args.write_reference:
            path.write_text(text, encoding="utf-8")
        elif path.read_text(encoding="utf-8").split() != text.split():
            parser.exit(1, "Walkthrough reference differs; run with --write-reference.\n")
        print("Walkthrough compatibility view matches its fragments.")
    else:
        print(compose(*args.sections))


if __name__ == "__main__":
    main()
