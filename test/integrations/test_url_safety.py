"""외부 URL의 SSRF 방어 정책을 검증한다."""

import socket

import pytest

from integrations.url_safety import UnsafeUrlError, validate_public_url


def dns_results(*addresses: str) -> list[tuple[object, ...]]:
    """테스트 IP 목록을 getaddrinfo 응답 형식으로 변환한다."""
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 0),
        )
        for address in addresses
    ]


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://8.8.8.8/notices", id="public-ipv4"),
        pytest.param(
            "https://[2606:4700:4700::1111]/notices",
            id="public-ipv6",
        ),
    ],
)
def test_validate_public_url_allows_public_ip(url: str) -> None:
    """공개 IPv4와 IPv6 주소를 허용한다."""
    validate_public_url(url)


def test_validate_public_url_allows_domain_with_public_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """모든 DNS 결과가 공개 IP인 도메인을 허용한다."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: dns_results("8.8.8.8", "1.1.1.1"),
    )

    validate_public_url("https://notices.example.com/board")


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://127.0.0.1", id="loopback-ipv4"),
        pytest.param("https://[::1]", id="loopback-ipv6"),
        pytest.param("https://10.0.0.1", id="private-10"),
        pytest.param("https://172.16.0.1", id="private-172"),
        pytest.param("https://192.168.0.1", id="private-192"),
        pytest.param("https://169.254.169.254", id="metadata"),
        pytest.param("https://[fc00::1]", id="unique-local-ipv6"),
        pytest.param("https://[fe80::1]", id="link-local-ipv6"),
        pytest.param("https://0.0.0.0", id="unspecified"),
        pytest.param("https://224.0.0.1", id="multicast"),
    ],
)
def test_validate_public_url_rejects_non_global_ip(url: str) -> None:
    """공개 인터넷 주소가 아닌 IP를 거부한다."""
    with pytest.raises(UnsafeUrlError, match="공개 IP"):
        validate_public_url(url)


def test_validate_public_url_rejects_mixed_dns_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS 결과에 사설 IP가 하나라도 포함되면 거부한다."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: dns_results("8.8.8.8", "127.0.0.1"),
    )

    with pytest.raises(UnsafeUrlError, match="공개 IP"):
        validate_public_url("https://notices.example.com")


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("ftp://example.com/file", id="ftp"),
        pytest.param("file:///etc/passwd", id="file"),
        pytest.param("https://user:password@example.com", id="userinfo"),
        pytest.param("https://example.com:8080", id="port"),
    ],
)
def test_validate_public_url_rejects_disallowed_url_shape(url: str) -> None:
    """허용하지 않는 스킴·인증정보·포트를 거부한다."""
    with pytest.raises(UnsafeUrlError):
        validate_public_url(url)


def test_validate_public_url_rejects_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DNS 조회에 실패한 도메인을 거부한다."""

    def raise_dns_error(*args: object, **kwargs: object) -> object:
        """테스트용 DNS 조회 실패를 발생시킨다."""
        raise socket.gaierror("DNS 실패")

    monkeypatch.setattr(socket, "getaddrinfo", raise_dns_error)

    with pytest.raises(UnsafeUrlError, match="DNS"):
        validate_public_url("https://notices.example.com")
