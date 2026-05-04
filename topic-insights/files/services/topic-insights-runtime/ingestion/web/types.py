from __future__ import annotations
from dataclasses import dataclass

@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    provider: str
    rank: int

class ProviderRateLimited(Exception):
    pass

class ProviderUnavailable(Exception):
    pass
