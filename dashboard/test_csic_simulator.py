import tempfile
from pathlib import Path
import unittest

from csic_simulator import (
    CSICRequest,
    LocalWAFReplayer,
    calculate_metrics,
    parse_csic_file,
)
from feature_diagnostics import percentile, summarize_values


SAMPLE = (
    b"GET http://example.invalid/tienda1/item.jsp?id=7 HTTP/1.1\r\n"
    b"User-Agent: Mozilla/5.0\r\n"
    b"Cookie: JSESSIONID=secret\r\n\r\n\r\n"
    b"POST http://outside.invalid/tienda1/login.jsp HTTP/1.1\r\n"
    b"User-Agent: Test Browser\r\n"
    b"Authorization: Bearer secret\r\n"
    b"Content-Type: application/x-www-form-urlencoded\r\n"
    b"Content-Length: 16\r\n\r\n"
    b"login=a&pwd=1234\r\n"
)


class CSICSimulatorTests(unittest.TestCase):
    def test_parser_separates_get_and_post_with_body(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_bytes(SAMPLE)
            requests = list(parse_csic_file(path, "NORMAL"))

        self.assertEqual([item.method for item in requests], ["GET", "POST"])
        self.assertEqual(requests[0].true_label, "NORMAL")
        self.assertEqual(requests[1].body, b"login=a&pwd=1234")

    def test_replayer_ignores_original_host_and_sensitive_headers(self):
        request = CSICRequest(
            method="POST",
            target="http://outside.invalid/private?q=1",
            headers={
                "user-agent": "Browser",
                "content-type": "application/x-www-form-urlencoded",
                "cookie": "secret",
                "authorization": "secret",
            },
            body=b"a=1",
            true_label="ATAQUE",
        )
        outgoing = LocalWAFReplayer.build_request(request)

        self.assertEqual(outgoing.full_url, "http://nginx:80/private?q=1")
        self.assertNotIn("Cookie", outgoing.headers)
        self.assertNotIn("Authorization", outgoing.headers)

    def test_confusion_metrics(self):
        metrics = calculate_metrics({"tn": 8, "fp": 2, "fn": 1, "tp": 9})
        self.assertAlmostEqual(metrics["accuracy"], 0.85)
        self.assertAlmostEqual(metrics["precision"], 9 / 11)
        self.assertAlmostEqual(metrics["recall"], 0.9)
        self.assertAlmostEqual(metrics["false_positive_rate"], 0.2)
        self.assertAlmostEqual(metrics["false_negative_rate"], 0.1)

    def test_replayer_reads_observational_values_from_waf_headers(self):
        headers = {
            "X-WAF-Risk": "0.6125",
            "X-WAF-Threshold": "0.44",
            "X-WAF-Feature-Names": ",".join(f"f{i}" for i in range(9)),
            "X-WAF-Feature-Limits": ",".join("10" for _ in range(9)),
            "X-WAF-Features-Raw": "5,11,0,1,2,3,4,5,6",
            "X-WAF-Features-Normalized": "0.5,1,0,0.1,0.2,0.3,0.4,0.5,0.6",
        }
        diagnostics = LocalWAFReplayer._diagnostics_from_headers(headers)

        self.assertEqual(diagnostics["risco"], 0.6125)
        self.assertEqual(diagnostics["threshold"], 0.44)
        self.assertEqual(len(diagnostics["features"]), 9)
        self.assertTrue(diagnostics["features"][1]["clipping"])
        self.assertFalse(diagnostics["features"][0]["clipping"])

    def test_statistics_and_clipping_use_raw_values(self):
        feature = {"nome": "query_length", "limite": 200, "tipo": "numerica"}
        summary = summarize_values([0, 100, 200, 300], feature)
        self.assertEqual(summary["media"], 150)
        self.assertEqual(summary["mediana"], 150)
        self.assertEqual(summary["maximo"], 300)
        self.assertEqual(summary["acima_limite"], 1)
        self.assertEqual(summary["percentual_clipping"], 0.25)
        self.assertAlmostEqual(percentile([0, 100, 200, 300], 0.95), 285)

if __name__ == "__main__":
    unittest.main()
