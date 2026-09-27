import hashlib
import unittest

from nexus1000 import (
    HttpsResponse,
    HttpsRetrievalPolicy,
    HttpsSourceResolver,
    RegisteredHttpsSource,
    RetrievalPolicyError,
)


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, pinned_ip, timeout_seconds, max_bytes):
        self.calls.append((url, pinned_ip, timeout_seconds, max_bytes))
        return self.responses.pop(0)


class TestHttpsSourceResolver(unittest.TestCase):
    def resolver(self, source, responses, *, addresses=("93.184.216.34",), **policy):
        transport = FakeTransport(responses)
        resolver = HttpsSourceResolver(
            (source,),
            HttpsRetrievalPolicy(allowed_domains=("evidence.example",), **policy),
            dns_resolver=lambda _host: addresses,
            transport=transport,
            clock=lambda: "2026-09-20T12:00:00+00:00",
        )
        return resolver, transport

    def test_registered_https_source_has_pinned_provenance(self):
        body = b"Survey found 82 percent intent to buy."
        source = RegisteredHttpsSource(
            "survey", "customer-research", "https://evidence.example/survey.txt", "text/plain"
        )
        resolver, transport = self.resolver(
            source,
            (HttpsResponse(200, {"content-type": "text/plain; charset=utf-8"}, body),),
        )

        retrieved = resolver("survey")

        self.assertEqual(retrieved.content, body.decode())
        self.assertEqual(retrieved.content_hash, hashlib.sha256(body).hexdigest())
        self.assertEqual(retrieved.location, "https://evidence.example/survey.txt")
        self.assertEqual(retrieved.retrieved_at, "2026-09-20T12:00:00+00:00")
        self.assertEqual(transport.calls[0][1], "93.184.216.34")

    def test_non_https_and_unallowlisted_domains_are_blocked_before_transport(self):
        for url, message in (
            ("http://evidence.example/a.txt", "HTTPS"),
            ("https://evil.example/a.txt", "allowlist"),
            ("https://evidence.example:444/a.txt", "port"),
        ):
            with self.subTest(url=url):
                source = RegisteredHttpsSource("s", "test", url, "text/plain")
                resolver, transport = self.resolver(source, ())
                with self.assertRaisesRegex(RetrievalPolicyError, message):
                    resolver("s")
                self.assertEqual(transport.calls, [])

    def test_private_or_local_dns_results_are_blocked(self):
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/a.txt", "text/plain"
        )
        for address in ("127.0.0.1", "10.0.0.2", "169.254.169.254", "::1"):
            with self.subTest(address=address):
                resolver, transport = self.resolver(source, (), addresses=(address,))
                with self.assertRaisesRegex(RetrievalPolicyError, "public IP"):
                    resolver("s")
                self.assertEqual(transport.calls, [])

        resolver, transport = self.resolver(
            source, (), addresses=("93.184.216.34", "10.0.0.2")
        )
        with self.assertRaisesRegex(RetrievalPolicyError, "public IP"):
            resolver("s")
        self.assertEqual(transport.calls, [])

    def test_every_redirect_is_revalidated(self):
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/start.txt", "text/plain"
        )
        resolver, transport = self.resolver(
            source,
            (HttpsResponse(302, {"location": "https://evil.example/stolen.txt"}, b""),),
        )
        with self.assertRaisesRegex(RetrievalPolicyError, "allowlist"):
            resolver("s")
        self.assertEqual(len(transport.calls), 1)

    def test_redirect_limit_is_enforced(self):
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/start.txt", "text/plain"
        )
        resolver, _transport = self.resolver(
            source,
            (
                HttpsResponse(302, {"location": "/one.txt"}, b""),
                HttpsResponse(302, {"location": "/two.txt"}, b""),
            ),
            max_redirects=1,
        )
        with self.assertRaisesRegex(RetrievalPolicyError, "redirect limit"):
            resolver("s")

    def test_allowed_relative_redirect_is_revalidated_and_followed(self):
        body = b"verified text"
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/start.txt", "text/plain"
        )
        resolver, transport = self.resolver(
            source,
            (
                HttpsResponse(302, {"location": "/final.txt"}, b""),
                HttpsResponse(200, {"content-type": "text/plain"}, body),
            ),
        )
        retrieved = resolver("s")
        self.assertEqual(retrieved.location, "https://evidence.example/final.txt")
        self.assertEqual(len(transport.calls), 2)

    def test_size_content_type_and_compression_are_enforced(self):
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/a.txt", "text/plain"
        )
        cases = (
            (HttpsResponse(200, {"content-type": "text/plain"}, b"123456"), {"max_bytes": 5}, "size limit"),
            (HttpsResponse(200, {"content-type": "text/html"}, b"hello"), {}, "content type"),
            (HttpsResponse(200, {"content-type": "text/plain", "content-encoding": "gzip"}, b"hello"), {}, "compression"),
        )
        for response, policy, message in cases:
            with self.subTest(message=message):
                resolver, _transport = self.resolver(source, (response,), **policy)
                with self.assertRaisesRegex(RetrievalPolicyError, message):
                    resolver("s")

    def test_unknown_source_is_not_fetched(self):
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/a.txt", "text/plain"
        )
        resolver, transport = self.resolver(source, ())
        self.assertIsNone(resolver("unknown"))
        self.assertEqual(transport.calls, [])

    def test_registered_html_is_blocked_until_safe_extraction_exists(self):
        source = RegisteredHttpsSource(
            "s", "test", "https://evidence.example/a.html", "text/html"
        )
        resolver, transport = self.resolver(source, ())
        with self.assertRaisesRegex(RetrievalPolicyError, "content type"):
            resolver("s")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
