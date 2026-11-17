"""Units of work stay short and independent: the property that lets SQLite writers queue instead of deadlocking.

SQLite files start every transaction with ``BEGIN IMMEDIATE`` (``db/session.py``), so a writer waits for the one before
it to commit. That is only safe while no unit of work waits for another unit of work, takes a lock, or waits on slow I/O
while it holds the write lock. This reads the source and fails when one does.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "sparta"
LOCKS = {"lock", "_locked"}
SLOW = {"sleep", "synthesize", "transcribe", "notify", "answer", "hangup", "say", "send", "request", "post"}


def _is_call_to(expr: ast.expr, names: set[str]) -> bool:
    return isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr in names


def units_of_work(tree: ast.AST) -> list[ast.AsyncWith]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncWith) and any(_is_call_to(item.context_expr, {"uow"}) for item in node.items)
    ]


def problems_in(source: str, name: str) -> list[str]:
    found: list[str] = []
    for unit in units_of_work(ast.parse(source)):
        for inner in ast.walk(unit):
            if inner is unit:
                continue
            if isinstance(inner, ast.AsyncWith):
                for item in inner.items:
                    if _is_call_to(item.context_expr, {"uow"}):
                        found.append(f"{name}:{inner.lineno}: a unit of work inside the one at line {unit.lineno}")
                    if _is_call_to(item.context_expr, LOCKS):
                        found.append(
                            f"{name}:{inner.lineno}: a lock taken inside the unit of work at line {unit.lineno}"
                        )
            if isinstance(inner, ast.Await) and isinstance(inner.value, ast.Call):
                func = inner.value.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if called in SLOW:
                    found.append(
                        f"{name}:{inner.lineno}: awaits '{called}' inside the unit of work at line {unit.lineno}"
                    )
    return found


def test_no_unit_of_work_nests_takes_a_lock_or_waits_on_slow_io():
    found = [
        problem
        for path in sorted(SRC.rglob("*.py"))
        for problem in problems_in(path.read_text(encoding="utf-8"), str(path.relative_to(SRC)))
    ]
    assert found == []


def test_the_scan_really_looks_at_the_units_of_work():
    count = sum(len(units_of_work(ast.parse(p.read_text(encoding="utf-8")))) for p in SRC.rglob("*.py"))
    assert count > 40  # a scan that silently matches nothing would pass forever


def test_the_scan_flags_each_kind_of_problem():
    nested = "async def f(db):\n    async with db.uow() as a:\n        async with db.uow() as b:\n            pass\n"
    locked = "async def f(db, kv):\n    async with db.uow() as a:\n        async with kv.lock('x'):\n            pass\n"
    slow = "async def f(db, tts):\n    async with db.uow() as a:\n        await tts.synthesize('hello')\n"
    fine = "async def f(db):\n    async with db.uow() as a:\n        await a.get_call_row('u', 'c')\n"
    assert len(problems_in(nested, "x")) == 1 and "inside the one" in problems_in(nested, "x")[0]
    assert len(problems_in(locked, "x")) == 1 and "lock" in problems_in(locked, "x")[0]
    assert len(problems_in(slow, "x")) == 1 and "synthesize" in problems_in(slow, "x")[0]
    assert problems_in(fine, "x") == []
