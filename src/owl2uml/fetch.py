"""Fetch ontology documents over HTTP(S), and find imports in XML catalogs.

``fetch`` is used both by the CLI (``--iri``, network imports) and by the web
app (the URL field, imports of uploaded files). On the server it must not be
usable to reach internal services, so with ``allow_private=False`` every host
on the redirect chain has to resolve to public addresses only.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ACCEPT = ("text/turtle, application/rdf+xml;q=0.9, application/owl+xml;q=0.8, "
          "text/owl-functional;q=0.7, text/owl-manchester;q=0.7, "
          "application/ld+json;q=0.6, text/plain;q=0.3, */*;q=0.1")
USER_AGENT = "owl2uml (ontology diagram tool)"
MAX_REDIRECTS = 5

# Content types that name a syntax unambiguously (see load.SYNTAXES).
CONTENT_TYPES = {
    "text/turtle": "turtle", "application/x-turtle": "turtle",
    "application/rdf+xml": "xml", "application/owl+xml": "owx",
    "text/owl-functional": "ofn", "text/owl-manchester": "omn",
    "application/ld+json": "json-ld", "application/n-triples": "nt",
    "text/n3": "n3", "application/trig": "trig",
}


class FetchError(ValueError):
    pass


@dataclass
class Fetched:
    data: bytes
    url: str            # final URL after redirects
    syntax: str | None  # from the Content-Type, when it names one


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - handled by caller
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _check_host(url: str, allow_private: bool) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"only http and https URLs can be loaded, not '{parts.scheme}:'")
    host = parts.hostname
    if not host:
        raise FetchError(f"no host in URL: {url}")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"cannot resolve host '{host}': {exc}") from None
    for info in infos:
        addr = ipaddress.ip_address(info[4][0].split("%")[0])
        if not addr.is_global:
            raise FetchError(f"refusing to load from a private or local address ({host})")


def fetch(url: str, *, max_bytes: int, timeout: float, allow_private: bool = True) -> Fetched:
    """GET ``url`` following up to 5 redirects, reading at most ``max_bytes``."""
    for _ in range(MAX_REDIRECTS + 1):
        _check_host(url, allow_private)
        req = urllib.request.Request(url, headers={"Accept": ACCEPT, "User-Agent": USER_AGENT})
        try:
            resp = _OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308) and exc.headers.get("Location"):
                url = urllib.parse.urljoin(url, exc.headers["Location"])
                continue
            raise FetchError(f"HTTP {exc.code} from {url}") from None
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise FetchError(f"could not load {url}: {reason}") from None
        with resp:
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise FetchError(f"{url} is larger than the {max_bytes // 2**20} MB limit")
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise FetchError(f"{url} is larger than the {max_bytes // 2**20} MB limit")
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return Fetched(data=data, url=resp.geturl() or url, syntax=CONTENT_TYPES.get(ctype))
    raise FetchError(f"too many redirects from {url}")


class Catalog:
    """An OASIS XML catalog (catalog-v001.xml, as written by Protégé and ODK).

    Supports ``uri`` and ``rewriteURI`` entries, inside ``group`` elements too,
    and follows ``nextCatalog``. Relative paths resolve against the catalog's
    own directory.
    """

    def __init__(self, path: str, _seen: set | None = None):
        self.path = os.path.abspath(path)
        self.uris: dict[str, str] = {}
        self.rewrites: list[tuple[str, str]] = []
        self.next: list[Catalog] = []
        seen = _seen if _seen is not None else set()
        seen.add(self.path)
        base = os.path.dirname(self.path)
        root = ET.parse(self.path).getroot()
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "uri" and el.get("name") and el.get("uri"):
                self.uris[el.get("name")] = self._local(base, el.get("uri"))
            elif tag == "rewriteURI" and el.get("uriStartString") and el.get("rewritePrefix"):
                self.rewrites.append((el.get("uriStartString"),
                                      self._local(base, el.get("rewritePrefix"))))
            elif tag == "nextCatalog" and el.get("catalog"):
                nxt = self._local(base, el.get("catalog"))
                if nxt not in seen and os.path.exists(nxt):
                    self.next.append(Catalog(nxt, seen))

    @staticmethod
    def _local(base: str, ref: str) -> str:
        if ref.startswith("file:"):
            return urllib.request.url2pathname(urllib.parse.urlsplit(ref).path)
        if "://" in ref:
            return ref
        return os.path.normpath(os.path.join(base, ref))

    def resolve(self, iri: str) -> str | None:
        """Local path (or remapped URL) for ``iri``, or None."""
        if iri in self.uris:
            return self.uris[iri]
        for start, prefix in sorted(self.rewrites, key=lambda r: -len(r[0])):
            if iri.startswith(start):
                rest = iri[len(start):]
                return prefix + rest if "://" in prefix else os.path.join(prefix, rest)
        for nxt in self.next:
            hit = nxt.resolve(iri)
            if hit:
                return hit
        return None
