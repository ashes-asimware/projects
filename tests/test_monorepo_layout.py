import unittest
from pathlib import Path


class MonorepoLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.services = [
            "ach_ingestion_service",
            "ledger_service",
            "remittance_ingestion_service",
            "pairing_service",
            "provider_ledger_service",
            "payout_service",
            "batch_builder_service",
            "reconciliation_service",
            "claim_system_adapter",
            "bank_statement_ingestion_service",
        ]

    def test_service_directories_and_dockerfiles_exist(self) -> None:
        for service in self.services:
            with self.subTest(service=service):
                service_dir = self.root / service
                self.assertTrue(service_dir.is_dir())
                self.assertTrue((service_dir / "Dockerfile").is_file())
                self.assertTrue((service_dir / "app" / "main.py").is_file())

    def test_shared_modules_exist(self) -> None:
        self.assertTrue((self.root / "shared" / "events").is_dir())
        self.assertTrue((self.root / "shared" / "servicebus").is_dir())
        self.assertTrue((self.root / "shared" / "events" / "schemas.py").is_file())
        self.assertTrue((self.root / "shared" / "servicebus" / "client.py").is_file())


if __name__ == "__main__":
    unittest.main()
