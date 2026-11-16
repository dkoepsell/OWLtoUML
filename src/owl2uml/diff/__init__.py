"""Visual version diff (spec WS4): ``owl2uml diff OLD NEW``."""
from .compare import FAIL_ON, changed, check, compare
from .report import markdown

__all__ = ["FAIL_ON", "changed", "check", "compare", "markdown"]
