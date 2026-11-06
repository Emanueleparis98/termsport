from __future__ import annotations

import hashlib
import ipaddress
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from urllib.parse import urlsplit, urlunsplit


SPORTS = {
    "calcio": ("football", "soccer", "calcio", "futbol"),
    "basket": ("basketball", "basket", "nba", "wnba"),
    "tennis": ("tennis", "atp", "wta"),
    "motori": ("motorsport", "formula", "moto", "racing", "nascar", "grand prix"),
    "hockey": ("hockey", "nhl"),
    "rugby": ("rugby",),
    "volley": ("volleyball", "volley"),
    "ciclismo": ("cycling", "ciclismo"),
    "combattimento": ("boxing", "mma", "ufc", "wrestling", "boxe", "fighting"),
    "baseball": ("baseball", "mlb"),
    "football americano": ("american football", "nfl", "ncaa football"),
    "cricket": ("cricket",),
    "golf": ("golf", "pga", "dp world tour"),
    "badminton": ("badminton", "bwf"),
    "snooker": ("snooker",),
    "esport": ("esport", "e-sport", "counter strike", "dota"),
    "pallamano": ("handball", "pallamano"),
    "futsal": ("futsal", "calcio a 5"),
    "sport invernali": ("winter sport", "skiing", "biathlon", "snowboard"),
    "ginnastica": ("gymnastics", "ginnastica"),
    "equitazione": ("equestrian", "equitazione"),
}


def plain(value: object, limit: int = 300) -> str:
    """Untrusted provider text is not terminal control sequences or Rich markup."""
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value or ""))
    return " ".join("".join(c for c in text if not unicodedata.category(c).startswith("C")).split())[:limit]


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


def sport_name(value: str) -> str:
    text = normalized(value)
    # American football must precede the more general football alias.
    if any(term in text for term in SPORTS["football americano"]):
        return "football americano"
    if any(term in text for term in SPORTS["futsal"]):
        return "futsal"
    for sport, aliases in SPORTS.items():
        if any(term in text for term in aliases):
            return sport
    return plain(value, 50) or "Altro"


def web_url(value: str, *, allow_local: bool = False) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Serve un indirizzo HTTP/HTTPS senza credenziali incorporate.")
    if any(ord(c) < 32 for c in value) or len(value) > 16000:
        raise ValueError("Indirizzo non valido.")
    if not allow_local:
        host = parts.hostname.casefold().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local")):
            raise ValueError("Gli indirizzi locali richiedono un’apertura esplicita.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address and not address.is_global:
            raise ValueError("Gli indirizzi privati richiedono un’apertura esplicita.")
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def timestamp(value: object) -> datetime | None:
    try:
        if isinstance(value, str) and value.isdigit():
            value = int(value)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None  # Never silently guess a provider timezone.
    except (ValueError, TypeError, OverflowError, OSError):
        return None


@dataclass
class Source:
    id: str
    name: str
    url: str
    sections: list[str] = field(default_factory=list)
    mirrors: list[str] = field(default_factory=list)
    notes: str = ""
    adapter: str = "generic"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    title: str
    sport: str
    source_id: str
    source_name: str
    url: str
    start: datetime | None = None
    live: bool = False
    competition: str = ""
    time_label: str = ""
    kind: str = "event"
    id: str = ""

    def __post_init__(self):
        self.title = plain(self.title)
        self.sport = sport_name(self.sport)
        self.competition = plain(self.competition)
        if not self.id:
            self.id = hashlib.sha256((self.source_id+":"+self.url).encode()).hexdigest()[:12]

    def matches(self, query: str, sport: str = "all", day: date | None = None) -> bool:
        if sport != "all" and normalized(self.sport) != normalized(sport):
            return False
        text = normalized(" ".join([self.title, self.sport, self.competition, self.source_name]))
        if not all(word in text for word in normalized(query).split()):
            # Translate a single Italian/English sport query without mutating event titles.
            if normalized(query) not in {normalized(self.sport), *SPORTS.get(self.sport, ())}:
                return False
        if day and self.start and self.start.astimezone().date() != day:
            return False
        return True

    def to_dict(self) -> dict:
        return {**asdict(self), "start": self.start.isoformat() if self.start else None}


@dataclass
class Stream:
    url: str
    label: str = "Diretta"
    kind: str = "page"  # hls / dash / video / page
    referer: str | None = None


@dataclass
class SourceResult:
    source: Source
    events: list[Event] = field(default_factory=list)
    status: str = "ok"
    detail: str = ""


def event_sort(event: Event):
    return (not event.live, event.start is None, event.start or datetime.max.replace(tzinfo=timezone.utc), event.title)
