import base64
import csv
import hashlib
import inspect
import json
import math
import sys
import unittest
from collections import Counter
from pathlib import Path


BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from construir_dataset import (
    SEED_EXPERIMENTO_2,
    reconstruct_reserved_request,
    select_development_indices,
    sha256_file,
)
from features_http import (
    FEATURES_EXPERIMENTO_2,
    extrair_features_experimento_2,
)


DATASETS = BASE / "datasets"
RESULTS = BASE / "resultados"
EXPECTED_CONTRACT_HASH = "def8e2461f2340e5bf0174da0ff633a6039045775fbb459b563dbc7f350615cd"


class FinalFeatureContractTests(unittest.TestCase):
    def test_order_is_frozen(self):
        digest = hashlib.sha256(("\n".join(FEATURES_EXPERIMENTO_2) + "\n").encode("ascii")).hexdigest()
        self.assertEqual(len(FEATURES_EXPERIMENTO_2), 76)
        self.assertEqual(len(set(FEATURES_EXPERIMENTO_2)), 76)
        self.assertEqual(digest, EXPECTED_CONTRACT_HASH)

    def test_vectors_are_fixed_length_finite_and_numeric(self):
        samples = (
            b"GET / HTTP/1.1\r\nHost: exemplo\r\n\r\n",
            b"POST http://localhost:8080/x?a=1 HTTP/1.1\r\nHost: localhost:8080\r\nContent-Type: application/x-www-form-urlencoded\r\nContent-Length: 3\r\n\r\nb=2",
            b"PUT http://localhost:abc/a.jpg/.Inc HTTP/1.1\r\nHost: localhost\r\n\r\n",
        )
        for raw in samples:
            vector = extrair_features_experimento_2(raw)
            self.assertEqual(len(vector), len(FEATURES_EXPERIMENTO_2))
            self.assertTrue(all(isinstance(value, float) and math.isfinite(value) for value in vector))

    def test_extractor_has_no_label_or_origin_argument(self):
        parameters = set(inspect.signature(extrair_features_experimento_2).parameters)
        self.assertEqual(parameters, {"source"})
        forbidden = {"label", "source_file", "source_sequence", "request_rate", "OpenServer", "xmlfile"}
        self.assertFalse(forbidden.intersection(FEATURES_EXPERIMENTO_2))

    def test_selection_is_reproducible(self):
        hashes = [hashlib.sha256(str(index).encode()).hexdigest() for index in range(100)]
        first = select_development_indices(hashes, "normal", 25, SEED_EXPERIMENTO_2)
        second = select_development_indices(hashes, "normal", 25, SEED_EXPERIMENTO_2)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 25)


class ConstructedDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.development = DATASETS / "csic_experimento2_desenvolvimento.csv"
        cls.reserved = DATASETS / "csic_experimento2_reservado.jsonl"
        cls.control = DATASETS / "controle_particoes.jsonl"
        cls.manifest = json.loads((RESULTS / "manifest_dataset.json").read_text(encoding="utf-8"))

    def test_development_csv_contract_counts_and_numeric_values(self):
        labels = Counter()
        row_count = 0
        with self.development.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            self.assertEqual(next(reader), [*FEATURES_EXPERIMENTO_2, "label"])
            for row in reader:
                self.assertEqual(len(row), len(FEATURES_EXPERIMENTO_2) + 1)
                numeric = [float(value) for value in row[:-1]]
                self.assertTrue(all(math.isfinite(value) for value in numeric))
                label = int(row[-1])
                self.assertIn(label, (0, 1))
                labels[label] += 1
                row_count += 1
        self.assertEqual(row_count, 30_000)
        self.assertEqual(labels, Counter({0: 15_000, 1: 15_000}))

    def test_control_proves_counts_no_overlap_and_no_loss(self):
        ids = {"development": set(), "reserved": set()}
        contents = {"development": set(), "reserved": set()}
        counts = Counter()
        with self.control.open("r", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                partition = record["partition"]
                ids[partition].add(record["record_id"])
                contents[partition].add(record["content_sha256"])
                counts[(partition, record["label"])] += 1
        self.assertEqual(counts[("development", 0)], 15_000)
        self.assertEqual(counts[("development", 1)], 15_000)
        self.assertEqual(counts[("reserved", 0)], 21_000)
        self.assertEqual(counts[("reserved", 1)], 10_065)
        self.assertEqual(len(ids["development"]), 30_000)
        self.assertEqual(len(ids["reserved"]), 31_065)
        self.assertFalse(ids["development"] & ids["reserved"])
        self.assertFalse(contents["development"] & contents["reserved"])
        self.assertEqual(len(ids["development"] | ids["reserved"]), 61_065)

    def test_reserved_is_traceable_and_reconstructable(self):
        labels = Counter()
        sequences = {0: [], 1: []}
        total = 0
        with self.reserved.open("r", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                self.assertTrue(record["target"])
                self.assertIn("raw_request_base64", record)
                self.assertIn("headers", record)
                self.assertIn("body_base64", record)
                labels[record["label"]] += 1
                sequences[record["label"]].append(record["source_sequence"])
                if total % 1000 == 0:
                    raw = reconstruct_reserved_request(record)
                    self.assertEqual(base64.b64encode(raw).decode("ascii"), record["raw_request_base64"])
                total += 1
        self.assertEqual(total, 31_065)
        self.assertEqual(labels, Counter({0: 21_000, 1: 10_065}))
        self.assertEqual(sequences[0], sorted(sequences[0]))
        self.assertEqual(sequences[1], sorted(sequences[1]))

    def test_manifest_matches_artifacts(self):
        self.assertEqual(self.manifest["seed"], SEED_EXPERIMENTO_2)
        self.assertEqual(self.manifest["features"]["ordem"], list(FEATURES_EXPERIMENTO_2))
        self.assertEqual(self.manifest["validacoes"]["sobreposicao_ids"], 0)
        self.assertEqual(self.manifest["validacoes"]["sobreposicao_conteudo"], 0)
        self.assertEqual(self.manifest["validacoes"]["requisicoes_perdidas"], 0)
        for key, path in (
            ("desenvolvimento", self.development),
            ("reservado", self.reserved),
            ("controle", self.control),
        ):
            self.assertEqual(self.manifest["arquivos"][key]["bytes"], path.stat().st_size)
            self.assertEqual(self.manifest["arquivos"][key]["sha256"], sha256_file(path))


if __name__ == "__main__":
    unittest.main()
