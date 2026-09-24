import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))

from features_http import FEATURE_DEFINITIONS, extrair_features_candidatas


class CandidateFeatureTests(unittest.TestCase):
    def test_path_with_extension_transition_is_preserved(self):
        raw = (
            b"GET http://localhost:8080/tienda1/imagenes/nuestratierra.jpg/.Inc HTTP/1.1\r\n"
            b"Host: localhost:8080\r\n\r\n"
        )
        features = extrair_features_candidatas(raw)
        self.assertEqual(features["path_segment_count"], 4.0)
        self.assertEqual(features["path_extension_like_segment_count"], 2.0)
        self.assertEqual(features["path_hidden_segment_count"], 1.0)
        self.assertEqual(features["path_nested_extension_transition"], 1.0)

    def test_invalid_port_is_not_replaced_by_zero(self):
        raw = b"GET http://localhost:abc/caminho HTTP/1.1\r\nHost: localhost\r\n\r\n"
        features = extrair_features_candidatas(raw)
        self.assertEqual(features["url_port_present"], 1.0)
        self.assertEqual(features["url_port_valid"], 0.0)
        self.assertIsNone(features["url_port_value"])

    def test_extractor_contract_has_no_label_or_request_rate(self):
        raw = (
            b"POST /x?a=1 HTTP/1.1\r\nContent-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: 3\r\n\r\nb=2"
        )
        features = extrair_features_candidatas(raw)
        self.assertEqual(set(features), set(FEATURE_DEFINITIONS))
        self.assertNotIn("label", features)
        self.assertNotIn("class_label", features)
        self.assertNotIn("request_rate", features)
        self.assertEqual(features["query_parameter_count"], 1.0)
        self.assertEqual(features["body_parameter_count"], 1.0)
        self.assertEqual(features["content_length_matches_body"], 1.0)

    def test_non_form_body_is_not_forced_into_parameters(self):
        raw = b"POST /x HTTP/1.1\r\nContent-Type: application/json\r\nContent-Length: 7\r\n\r\n{\"a\":1}"
        features = extrair_features_candidatas(raw)
        self.assertEqual(features["body_present"], 1.0)
        self.assertEqual(features["body_length_raw"], 7.0)
        self.assertIsNone(features["body_parameter_count"])


if __name__ == "__main__":
    unittest.main()
