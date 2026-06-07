"""errors.py — domain errors, mapped to HTTP status in main.py.

Seams raise these; they never import FastAPI. main.py owns the HTTP translation
so the domain layer stays transport-agnostic.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base for all seam-raised errors. status is the HTTP code main.py emits."""

    status: int = 400


class AuthError(DomainError):
    status = 401


class ForbiddenError(DomainError):
    status = 403


class NotFoundError(DomainError):
    status = 404


class ConflictError(DomainError):
    """Invariant violation — e.g. attempting to overwrite a locked node."""

    status = 409
