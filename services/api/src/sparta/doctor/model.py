"""Result model of the provider preflight (``python -m sparta doctor``).

Every check ends in one of four states and the difference matters:

* ``PASS``       something was actually checked and is fine;
* ``WARNING``    works, but is risky, wasteful or probably not what was meant;
* ``BLOCKED``    a real call cannot work until this is fixed;
* ``UNVERIFIED`` it cannot be proven from here (it needs a portal step, a real call or a billable probe): the check says
  exactly how it can be proven. UNVERIFIED is never a pass.

Nothing in this module (or in any check) may carry a secret value: details are written by hand without values and every
rendered string is passed through :func:`sparta.logging_setup.redact_text` as a last line of defence.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sparta.logging_setup import redact_text


class Status(StrEnum):
    PASS = "PASS"  # noqa: S105  # nosec B105 - a status name, not a password
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    UNVERIFIED = "UNVERIFIED"


_ORDER = {Status.BLOCKED: 0, Status.WARNING: 1, Status.UNVERIFIED: 2, Status.PASS: 3}
_COLOUR = {Status.PASS: "32", Status.WARNING: "33", Status.BLOCKED: "31", Status.UNVERIFIED: "36"}


@dataclass(frozen=True)
class Check:
    id: str  # stable machine id such as "acs.connection_string"
    group: str
    title: str
    status: Status
    detail: str = ""  # what was found, without any value that could be a secret
    fix: str = ""  # what to do next

    def safe(self) -> "Check":
        return Check(self.id, self.group, self.title, self.status, redact_text(self.detail), redact_text(self.fix))


@dataclass
class DoctorReport:
    checks: list[Check] = field(default_factory=list)
    providers: tuple[str, ...] = ()
    online: bool = False
    billable: bool = False

    def add(self, check: Check) -> None:
        self.checks.append(check.safe())

    def extend(self, checks: list[Check]) -> None:
        for check in checks:
            self.add(check)

    def counts(self) -> dict[Status, int]:
        counted = Counter(check.status for check in self.checks)
        return {status: counted.get(status, 0) for status in Status}

    @property
    def blocked(self) -> bool:
        return any(check.status is Status.BLOCKED for check in self.checks)

    def exit_code(self) -> int:
        """0 when nothing is BLOCKED, 1 otherwise. WARNING and UNVERIFIED never fail the command."""
        return 1 if self.blocked else 0

    def verdict(self) -> str:
        counts = self.counts()
        if counts[Status.BLOCKED]:
            return f"NOT READY: {counts[Status.BLOCKED]} blocked"
        pending = counts[Status.UNVERIFIED]
        if pending:
            return f"NO BLOCKERS FOUND, but {pending} item(s) cannot be proven without a live call or a portal step"
        return "NO BLOCKERS FOUND"

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": list(self.providers),
            "online": self.online,
            "billable_probes": self.billable,
            "summary": {status.value: n for status, n in self.counts().items()},
            "verdict": self.verdict(),
            "checks": [
                {
                    "id": c.id,
                    "group": c.group,
                    "title": c.title,
                    "status": c.status.value,
                    "detail": c.detail,
                    "fix": c.fix,
                }
                for c in self.checks
            ],
        }

    def render_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"

    def render_text(self, *, colour: bool = False) -> str:
        def paint(status: Status) -> str:
            label = f"{status.value:<10}"
            return f"\x1b[{_COLOUR[status]}m{label}\x1b[0m" if colour else label

        lines = [
            "Sparta provider preflight"
            f" (providers: {', '.join(self.providers) or 'none'};"
            f" network checks: {'on' if self.online else 'off'};"
            f" billable probes: {'on' if self.billable else 'off'})",
            "No secret value is ever printed. PASS = checked, WARNING = risky, BLOCKED = a real call cannot work,",
            "UNVERIFIED = cannot be proven from here (the line says how).",
            "",
        ]
        groups: dict[str, list[Check]] = {}
        for check in self.checks:
            groups.setdefault(check.group, []).append(check)
        for group, checks in groups.items():
            lines.append(group)
            for check in sorted(checks, key=lambda c: (_ORDER[c.status], c.id)):
                lines.append(f"  {paint(check.status)} {check.title}")
                if check.detail:
                    lines.append(f"             {check.detail}")
                if check.fix and check.status is not Status.PASS:
                    lines.append(f"             -> {check.fix}")
            lines.append("")
        counts = self.counts()
        order = (Status.PASS, Status.WARNING, Status.BLOCKED, Status.UNVERIFIED)
        lines.append("Summary: " + ", ".join(f"{counts[s]} {s.value}" for s in order))
        lines.append(f"Verdict: {self.verdict()}")
        return "\n".join(lines) + "\n"
