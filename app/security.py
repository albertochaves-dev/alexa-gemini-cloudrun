import base64
import re
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

CERT_URL_PATTERN = re.compile(r"^https://s3\.amazonaws\.com(:443)?/echo\.api/")
TIMESTAMP_TOLERANCE_SECONDS = 150

_cert_cache: dict[str, bytes] = {}


def _get_certificate(cert_url: str) -> x509.Certificate:
    pem = _cert_cache.get(cert_url)
    if pem is None:
        response = httpx.get(cert_url, timeout=5.0)
        response.raise_for_status()
        pem = response.content
        _cert_cache[cert_url] = pem
    return x509.load_pem_x509_certificate(pem)


def verify_alexa_signature(cert_url: str, signature_b64: str, body: bytes) -> bool:
    try:
        if not CERT_URL_PATTERN.match(cert_url):
            return False
        cert = _get_certificate(cert_url)
        now = datetime.now(timezone.utc)
        if now < cert.not_valid_before_utc or now > cert.not_valid_after_utc:
            return False
        public_key = cert.public_key()
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, body, padding.PKCS1v15(), hashes.SHA1())
        return True
    except (InvalidSignature, ValueError, httpx.HTTPError):
        return False


def verify_timestamp(timestamp_str: str) -> bool:
    try:
        request_time = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return abs((now - request_time).total_seconds()) <= TIMESTAMP_TOLERANCE_SECONDS


class RateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True
