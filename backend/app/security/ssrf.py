"""SSRF checks for user-controlled outbound HTTP.

Literal addresses and DNS answers are rejected when they fall in loopback,
private, link-local, reserved, multicast, or unspecified ranges. Redirects must
be passed through ``validate_url`` again by the caller.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from app.errors import PermanentError

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "metadata.google.com",
    "instance-data",
    "instance-data.ec2.internal",
}


class SSRFError(PermanentError):
    pass


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        return _blocked_ip(mapped)
    if ip.version == 6 and ip == ipaddress.ip_address("fd00:ec2::254"):
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = host.strip().lower()
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    if candidate.isdigit():
        number = int(candidate)
        if 0 <= number <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(number)
    if candidate.startswith("0x"):
        try:
            number = int(candidate, 16)
        except ValueError:
            return None
        if 0 <= number <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(number)
    return None


def validate_url(url: str) -> str:
    """Return the normalized hostname or raise ``SSRFError``."""
    if not url or len(url) > 2000 or "\\" in url:
        raise SSRFError("URL is not allowed")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise SSRFError("Only http and https URLs are allowed")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise SSRFError("Credentials in URLs are not allowed")
    if "%" in parsed.netloc:
        raise SSRFError("Encoded hosts are not allowed")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL host is missing")
    host_l = host.lower().rstrip(".")
    if (
        host_l in BLOCKED_HOSTNAMES
        or host_l.endswith(".localhost")
        or host_l.endswith(".local")
        or host_l.endswith(".internal")
        or host_l.endswith(".localdomain")
    ):
        raise SSRFError("Host is not allowed")

    literal = _literal_ip(host_l)
    if literal is not None:
        if _blocked_ip(literal):
            raise SSRFError("Address is not allowed")
        return host_l

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host_l, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError("Host could not be resolved") from exc
    if not infos:
        raise SSRFError("Host could not be resolved")
    for info in infos:
        ip_text = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise SSRFError("Resolved address is not allowed") from exc
        if _blocked_ip(ip):
            raise SSRFError("Resolved address is not allowed")
    return host_l
