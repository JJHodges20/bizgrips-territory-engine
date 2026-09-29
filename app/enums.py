"""Canonical enumerations shared by configuration, models, services and the API.

Keep this module free of third-party imports so any layer can use it.
"""

from __future__ import annotations

from enum import StrEnum


class TerritoryStatus(StrEnum):
    """Lifecycle of a territory record (see BIZGRIPS_TERRITORY_STANDARD.md sections 8-11)."""

    PROPOSED = "PROPOSED"
    RESERVED = "RESERVED"
    ACTIVE_PROTECTED = "ACTIVE_PROTECTED"
    PENDING_RELEASE = "PENDING_RELEASE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(StrEnum):
    """Status of one ZIP inside a territory."""

    RESERVED = "RESERVED"
    ACTIVE_PROTECTED = "ACTIVE_PROTECTED"
    PENDING_RELEASE = "PENDING_RELEASE"
    RELEASED = "RELEASED"


class ZipAvailability(StrEnum):
    """Derived ZIP-level state shown to sales. AVAILABLE means no blocking assignment exists."""

    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ACTIVE_PROTECTED = "ACTIVE_PROTECTED"
    PENDING_RELEASE = "PENDING_RELEASE"


class TerritorySizeClass(StrEnum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"


class MarketTier(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    U = "U"  # unscored


# Statuses that make a ZIP unavailable to another client. The database partial unique index
# `uq_active_zip` is built from this tuple; `registry.blocking_statuses` in business_rules.yaml
# must stay consistent with it (validated by app.config.business_rules).
BLOCKING_ASSIGNMENT_STATUSES: tuple[AssignmentStatus, ...] = (
    AssignmentStatus.RESERVED,
    AssignmentStatus.ACTIVE_PROTECTED,
    AssignmentStatus.PENDING_RELEASE,
)
