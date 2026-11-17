"""
Canonical event asset categories.

Single source of truth for the 10 semantic categories used across the
Content Engine backend, API, and frontend.

Categories:
  event_venue — halls, centers, buildings, stages, rooms
  people      — persons, crowds, attendees, groups
  speakers    — presenters, hosts, panels, lecturers
  booths      — exhibits, stands, kiosks, displays
  products    — products, demos, merchandise, showcases
  branding    — logos, brand marks
  signage     — signs, banners, posters
  promotional — flyers, brochures, announcements, programs
  other       — recognized asset that does not fit a specific category
  uncertain   — insufficient signal to classify

The distinction between ``other`` and ``uncertain`` matters:
  - ``other``   = we have enough signal to know the asset is a real event
                  asset, but it does not match any specific category.
  - ``uncertain`` = we do not have enough signal to make any determination.
                  Never silently coerce uncertain → other.
"""

from typing import Dict, List, Optional, Set


# ── Canonical category identifiers ──────────────────────────────────────────

EVENT_VENUE   = "event_venue"
PEOPLE        = "people"
SPEAKERS      = "speakers"
BOOTHS        = "booths"
PRODUCTS      = "products"
BRANDING      = "branding"
SIGNAGE       = "signage"
PROMOTIONAL   = "promotional"
OTHER         = "other"
UNCERTAIN     = "uncertain"

ALL_CATEGORIES: List[str] = [
    EVENT_VENUE,
    PEOPLE,
    SPEAKERS,
    BOOTHS,
    PRODUCTS,
    BRANDING,
    SIGNAGE,
    PROMOTIONAL,
    OTHER,
    UNCERTAIN,
]

SPECIFIC_CATEGORIES: Set[str] = {
    EVENT_VENUE, PEOPLE, SPEAKERS, BOOTHS, PRODUCTS,
    BRANDING, SIGNAGE, PROMOTIONAL,
}

# Categories that imply "we have enough signal to classify"
CONFIDENT_CATEGORIES: Set[str] = SPECIFIC_CATEGORIES | {OTHER}

# ── Human-readable labels ───────────────────────────────────────────────────

CATEGORY_LABELS: Dict[str, str] = {
    EVENT_VENUE:   "Event Venue",
    PEOPLE:        "People",
    SPEAKERS:      "Speakers",
    BOOTHS:        "Booths",
    PRODUCTS:      "Products",
    BRANDING:      "Branding",
    SIGNAGE:       "Signage",
    PROMOTIONAL:   "Promotional",
    OTHER:         "Other",
    UNCERTAIN:     "Unclassified",
}

# ── Keyword mapping from detected labels to categories ──────────────────────
#
# Each keyword maps to the category it most strongly indicates. Keywords are
# matched case-insensitively against Florence-2 object detection labels and
# CLIP concept names. The mapping is intentionally conservative: a label must
# contain the keyword as a substring to match.
#
# NOTE: "branding" (logos/brand marks) and "signage" (signs/banners/posters)
# are kept separate per the canonical definition. A detected "logo" maps to
# branding; a detected "sign"/"banner"/"poster" maps to signage.

_LABEL_TO_CATEGORY: Dict[str, str] = {
    # event_venue
    "stage": EVENT_VENUE,
    "podium": EVENT_VENUE,
    "hall": EVENT_VENUE,
    "center": EVENT_VENUE,
    "centre": EVENT_VENUE,
    "building": EVENT_VENUE,
    "venue": EVENT_VENUE,
    "room": EVENT_VENUE,
    "auditorium": EVENT_VENUE,
    "theater": EVENT_VENUE,
    "theatre": EVENT_VENUE,
    "conference room": EVENT_VENUE,
    "ballroom": EVENT_VENUE,

    # people
    "person": PEOPLE,
    "people": PEOPLE,
    "crowd": PEOPLE,
    "audience": PEOPLE,
    "attendee": PEOPLE,
    "attendees": PEOPLE,
    "group": PEOPLE,
    "crowd": PEOPLE,

    # speakers
    "speaker": SPEAKERS,
    "presenter": SPEAKERS,
    "host": SPEAKERS,
    "panel": SPEAKERS,
    "lecturer": SPEAKERS,
    "guest": SPEAKERS,
    "moderator": SPEAKERS,

    # booths
    "booth": BOOTHS,
    "exhibit": BOOTHS,
    "stand": BOOTHS,
    "kiosk": BOOTHS,
    "counter": BOOTHS,
    "table": BOOTHS,
    "display": BOOTHS,

    # products
    "product": PRODUCTS,
    "demo": PRODUCTS,
    "merchandise": PRODUCTS,
    "showcase": PRODUCTS,
    "launch": PRODUCTS,
    "item": PRODUCTS,

    # branding
    "logo": BRANDING,
    "brand": BRANDING,
    "brand mark": BRANDING,

    # signage
    "sign": SIGNAGE,
    "banner": SIGNAGE,
    "poster": SIGNAGE,
    "signage": SIGNAGE,

    # promotional
    "flyer": PROMOTIONAL,
    "brochure": PROMOTIONAL,
    "announcement": PROMOTIONAL,
    "program": PROMOTIONAL,
    "handout": PROMOTIONAL,
}


def label_to_category(label: str) -> Optional[str]:
    """
    Map a single detected label to a canonical category.

    Returns None when the label does not match any known keyword — the caller
    should then treat the signal as uninformative rather than forcing a
    category.
    """
    key = label.strip().lower()
    return _LABEL_TO_CATEGORY.get(key)


def labels_to_categories(labels: List[str]) -> Dict[str, int]:
    """
    Count category votes from a list of detected labels.

    Returns {category: vote_count} for categories that received at least one
    vote. Labels that do not map to any category are ignored.
    """
    votes: Dict[str, int] = {}
    for label in labels:
        cat = label_to_category(label)
        if cat is not None:
            votes[cat] = votes.get(cat, 0) + 1
    return votes


def is_valid_category(value: Optional[str]) -> bool:
    """Return True when value is one of the canonical category identifiers."""
    return value in ALL_CATEGORIES


def normalize_category(value: Optional[str], default: str = UNCERTAIN) -> str:
    """
    Normalize an arbitrary category string to a canonical identifier.

    Unknown values are returned as ``default`` (which defaults to
    ``UNCERTAIN``). They are NOT silently coerced to ``other`` — the caller
    decides whether an unrecognized value should be ``other`` or ``uncertain``.
    """
    if value is None:
        return default
    if is_valid_category(value):
        return value
    return default


def category_label(category: str) -> str:
    """Return the human-readable label for a canonical category."""
    return CATEGORY_LABELS.get(category, category)


def category_icon(category: str) -> str:
    """
    Return a lucide-react icon name for a canonical category.

    Used by the frontend AssetSelectionPage. Unknown categories map to
    ``"HelpCircle"`` (explicit Unknown/Unclassified state).
    """
    return {
        EVENT_VENUE:   "Building",
        PEOPLE:        "Users",
        SPEAKERS:      "Mic",
        BOOTHS:        "Store",
        PRODUCTS:      "Package",
        BRANDING:      "Tag",
        SIGNAGE:       "Flag",
        PROMOTIONAL:   "Megaphone",
        OTHER:         "Folder",
        UNCERTAIN:     "HelpCircle",
    }.get(category, "HelpCircle")
