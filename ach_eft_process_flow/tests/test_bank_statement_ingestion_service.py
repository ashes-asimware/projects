import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_TEST_DATABASE_URL = "sqlite:///:memory:"


def _make_test_app():
    import bank_statement_ingestion_service.app.db as db_module
    import bank_statement_ingestion_service.app.main as main_module

    test_engine = create_engine(
        _TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    db_module.engine = test_engine
    db_module.SessionLocal = TestSessionLocal
    main_module.engine = test_engine
    main_module.SessionLocal = TestSessionLocal

    from bank_statement_ingestion_service.app.db import Base
    import bank_statement_ingestion_service.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from bank_statement_ingestion_service.app.main import app, get_db

    app.dependency_overrides[get_db] = override_get_db
    return app, TestSessionLocal, test_engine


class BankStatementIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self.SessionLocal, self.engine = _make_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        from bank_statement_ingestion_service.app.db import Base
        from bank_statement_ingestion_service.app.main import app, get_db

        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=self.engine)
        os.environ.pop("DATABASE_URL", None)

    def test_ingest_bai2_publishes_bank_statement_event(self) -> None:
        bai2_text = "01,STAT123,\n02,PAYER1,PROVIDER1,\n16,475,15000,"
        with patch("bank_statement_ingestion_service.app.main.publisher.send", return_value=True) as send_mock:
            response = self.client.post("/ingest-bai2", json={"bai2_data": bai2_text})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["trace_number"], "STAT123")
        self.assertEqual(data["claims"][0]["amount_cents"], 15000)
        send_mock.assert_called_once()
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], "bank_statement_queue")

    def test_ingest_camt053_handles_xml_and_publishes(self) -> None:
        camt_xml = """
        <Document>
          <Stmt>
            <Id>STMT-ABC</Id>
            <Ntry>
              <Amt>1234</Amt>
              <CdtDbtInd>CRDT</CdtDbtInd>
              <NtryDtls><TxDtls><Refs><TxId>TX-555</TxId></Refs></TxDtls></NtryDtls>
            </Ntry>
          </Stmt>
          <Cdtr><Nm>payer-xyz</Nm></Cdtr>
          <CdtrAcct><Id><IBAN>provider-789</IBAN></Id></CdtrAcct>
        </Document>
        """
        with patch("bank_statement_ingestion_service.app.main.publisher.send", return_value=True) as send_mock:
            response = self.client.post("/ingest-camt053", json={"camt053_xml": camt_xml})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["trace_number"], "TX-555")
        self.assertEqual(data["provider_id"], "provider-789")
        send_mock.assert_called_once()
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], "bank_statement_queue")


if __name__ == "__main__":
    unittest.main()
