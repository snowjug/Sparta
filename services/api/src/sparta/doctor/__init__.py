"""Provider preflight: ``python -m sparta doctor``. See :mod:`sparta.doctor.runner`."""

from sparta.doctor.model import Check, DoctorReport, Status
from sparta.doctor.runner import run_doctor

__all__ = ["Check", "DoctorReport", "Status", "run_doctor"]
