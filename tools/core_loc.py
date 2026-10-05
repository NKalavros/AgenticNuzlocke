"""Count physical source lines with Python tokens, excluding comments and docstrings.

All Python under nuzlocke/ and apps/ counts, including loaders, adapters and
walkthrough selectors. Non-Python content, tests and tools do not count.
Delimiter-only source lines count. There are no per-file exemptions.
"""

import argparse
import ast
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 12_000


def source_lines(source: str) -> int:
    tree = ast.parse(source)
    rows = source.splitlines()

    def position(line, byte_column):
        # AST columns are UTF-8 bytes; tokenize columns are Unicode characters.
        return line, len(rows[line - 1].encode("utf-8")[:byte_column].decode("utf-8"))

    docs = []
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and ast.get_docstring(node, clean=False) is not None
        ):
            doc = node.body[0]
            docs.append((position(doc.lineno, doc.col_offset), position(doc.end_lineno, doc.end_col_offset)))
    excluded = {
        tokenize.ENDMARKER,
        tokenize.NEWLINE,
        tokenize.NL,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.COMMENT,
        tokenize.ENCODING,
    }
    lines = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in excluded and not any(start <= token.start < end for start, end in docs):
            lines.update(range(token.start[0], token.end[0] + 1))
    return len(lines)


def counts(root: Path = ROOT) -> dict[str, int]:
    return {
        str(path.relative_to(root)): source_lines(path.read_text(encoding="utf-8"))
        for directory in ("nuzlocke", "apps")
        for path in sorted((root / directory).rglob("*.py"))
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help=f"Fail at {LIMIT:,} lines or more")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = counts(args.root)
    for name, count in sorted(result.items(), key=lambda row: (-row[1], row[0])):
        print(f"{count:5} {name}")
    total = sum(result.values())
    print(f"Core Python: {total:,} source lines; required: < {LIMIT:,}")
    raise SystemExit(int(args.check and total >= LIMIT))
