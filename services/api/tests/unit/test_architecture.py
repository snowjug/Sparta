"""The import direction that docs/DECISIONS/0001-modular-monolith.md promises, checked on the source itself."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "sparta"

# package -> packages it must never import (the ADR: pure domain logic does not know about I/O or HTTP)
FORBIDDEN = {
    "domain": {
        "api",
        "db",
        "language",
        "observability",
        "orchestrator",
        "providers",
        "risk",
        "services",
        "telephony",
    },
    "language": {"api", "db", "orchestrator", "providers", "risk", "services", "telephony"},
    "risk": {"api", "db", "orchestrator", "providers", "services", "telephony"},
    "orchestrator": {"api", "db", "services", "telephony"},
    "providers": {"api", "services"},
    "telephony": {"api", "services"},
    "db": {"api", "orchestrator", "services", "telephony"},
}


def sparta_imports(path: Path) -> set[str]:
    """Top-level ``sparta`` subpackages imported by one module (absolute and relative imports)."""
    found: set[str] = set()
    package = path.relative_to(SRC).parts[:-1]
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative import: resolve against this module's package
                base = list(package[: len(package) - (node.level - 1)])
                parts = base + (node.module.split(".") if node.module else [])
            else:
                parts = (node.module or "").split(".")
                if parts[0] != "sparta":
                    continue
                parts = parts[1:]
            if parts:
                found.add(parts[0])
            elif node.level == 0 or not parts:  # `from sparta import x`
                found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")
                if head[0] == "sparta" and len(head) > 1:
                    found.add(head[1])
    return found


@pytest.mark.parametrize("package", sorted(FORBIDDEN))
def test_packages_only_import_in_the_documented_direction(package):
    modules = sorted((SRC / package).rglob("*.py"))
    assert modules, f"no modules found under {SRC / package}"
    violations = {
        str(module.relative_to(SRC)): sorted(sparta_imports(module) & FORBIDDEN[package])
        for module in modules
        if sparta_imports(module) & FORBIDDEN[package]
    }
    assert not violations, f"{package} must not import {sorted(FORBIDDEN[package])}: {violations}"


def test_the_checker_itself_finds_imports():
    assert "domain" in sparta_imports(SRC / "risk" / "matchers.py")
    assert "language" in sparta_imports(SRC / "risk" / "matchers.py")
