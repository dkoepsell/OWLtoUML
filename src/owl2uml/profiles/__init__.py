"""Notation profiles (spec WS3): declarative files that say how to draw
specific relations and class kinds, so a BFO or legal ontology reads in its
own idiom.

    profile = load("bfo,legal", graph)     # bundled names or file paths
    apply(model, profile, graph)           # between parsing and rendering

See docs/profiles.md for the format.
"""
from .loader import Profile, ProfileError, available, detect, load  # noqa: F401
from .apply import apply, finish, label_count  # noqa: F401
