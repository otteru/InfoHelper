"""외부 URL의 SSRF 안전성을 검증한다."""

import socket
from ipaddress import IPv4Address, IPv6Address, ip_address
from urllib.parse import SplitResult, urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})

IPAddress = IPv4Address | IPv6Address


class UnsafeUrlError(ValueError):
    """외부 요청에 허용할 수 없는 URL이다."""


def validate_public_url(url: str) -> None:
    """URL이 공개 HTTP(S) 주소로만 연결되는지 검증한다."""
    parsed = _parse_url(url)
    hostname = parsed.hostname

    if hostname is None:
        raise UnsafeUrlError("URL에 hostname이 필요합니다.")

    addresses = _resolve_addresses(hostname)
    if any(not _is_public_address(address) for address in addresses):
        raise UnsafeUrlError("URL은 공개 IP로만 연결되어야 합니다.")


def _parse_url(url: str) -> SplitResult:
    """URL 형태와 허용된 스킴·인증정보·포트를 검증한다."""
    if not isinstance(url, str) or not url or url != url.strip():
        raise UnsafeUrlError("올바른 URL 문자열이 필요합니다.")

    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise UnsafeUrlError("URL 형식이 올바르지 않습니다.") from error

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("http 또는 https URL만 허용합니다.")

    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("인증정보가 포함된 URL은 허용하지 않습니다.")

    if port is not None and port not in ALLOWED_PORTS:
        raise UnsafeUrlError("80 또는 443 포트만 허용합니다.")

    return parsed


def _resolve_addresses(hostname: str) -> tuple[IPAddress, ...]:
    """hostname이 가리키는 모든 IPv4·IPv6 주소를 반환한다."""
    try:
        return (ip_address(hostname),)
    except ValueError:
        pass

    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
        results = socket.getaddrinfo(
            ascii_hostname,
            None,
            type=socket.SOCK_STREAM,
        )
    except (OSError, UnicodeError) as error:
        raise UnsafeUrlError("URL hostname의 DNS 조회에 실패했습니다.") from error

    try:
        addresses = tuple(
            dict.fromkeys(ip_address(result[4][0]) for result in results)
        )
    except (IndexError, TypeError, ValueError) as error:
        raise UnsafeUrlError("DNS 조회 결과가 올바르지 않습니다.") from error

    if not addresses:
        raise UnsafeUrlError("URL hostname의 DNS 결과가 없습니다.")

    return addresses


def _is_public_address(address: IPAddress) -> bool:
    """일반 외부 HTTP 요청에 허용할 공개 IP인지 판별한다."""
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )
