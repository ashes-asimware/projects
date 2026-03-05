import hashlib
import json
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import ClaimReference, RemittanceReceivedV1
from shared.events.topics import REMITTANCE_RECEIVED_TOPIC
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import ProcessingRecord
from .schemas import ClaimDetail, Parsed835Data, RemittanceIngest835Request


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="remittance_ingestion_service", lifespan=lifespan)
apply_common_middleware(app)
publisher = ServiceBusPublisher()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "remittance_ingestion_service"}


def _parse_835(raw_835: str) -> Parsed835Data:
    try:
        parsed = json.loads(raw_835)
        if isinstance(parsed, dict):
            return Parsed835Data(**parsed)
    except (json.JSONDecodeError, ValidationError):
        pass

    return _parse_x12_835(raw_835)


def _parse_x12_835(x12_text: str) -> Parsed835Data:
    segment_terminator = "~"
    element_separator = "*"

    segments = [
        seg.strip()
        for seg in x12_text.split(segment_terminator)
        if seg.strip()
    ]

    trace_number = ""
    payer_id = ""
    provider_id = ""
    claims: list[ClaimDetail] = []
    in_payer_loop = False
    in_provider_loop = False

    for segment in segments:
        elements = segment.split(element_separator)
        segment_id = elements[0].strip()

        if segment_id == "TRN" and len(elements) > 2:
            trace_number = elements[2].strip()

        elif segment_id == "N1":
            qualifier = elements[1].strip() if len(elements) > 1 else ""
            in_payer_loop = qualifier == "PR"
            in_provider_loop = qualifier == "PE"
            if in_payer_loop and len(elements) > 4:
                payer_id = elements[4].strip()
            elif in_provider_loop and len(elements) > 4:
                provider_id = elements[4].strip()

        elif segment_id in {"N3", "N4", "REF", "PER"}:
            # N3=address, N4=city/state/zip, REF=reference ID, PER=contact info
            # These segments are not needed for claim-level remittance processing
            pass

        elif segment_id == "CLP" and len(elements) > 3:
            claim_id = elements[1].strip()
            try:
                if len(elements) > 4:
                    paid_amount = float(elements[4].strip())
                else:
                    paid_amount = float(elements[3].strip())
                amount_cents = round(paid_amount * 100)
            except ValueError:
                amount_cents = 0
            claims.append(ClaimDetail(claim_id=claim_id, amount_cents=amount_cents))

    return Parsed835Data(
        trace_number=trace_number,
        payer_id=payer_id,
        provider_id=provider_id,
        claims=claims,
    )


def _build_correlation_id(parsed_data: Parsed835Data) -> str:
    correlation_source = (
        f"{parsed_data.trace_number}|{parsed_data.payer_id}|{parsed_data.provider_id}"
    )
    return hashlib.sha256(correlation_source.encode("utf-8")).hexdigest()


def _extract_remittance_payload(
    request_body: RemittanceIngest835Request | None,
    remittance_file: UploadFile | None,
    remittance_text: str | None,
) -> str:
    if request_body and request_body.raw_835:
        return request_body.raw_835
    if remittance_text:
        return remittance_text
    if remittance_file is not None:
        file_bytes = remittance_file.file.read()
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("utf-8", errors="ignore")
    raise HTTPException(
        status_code=422,
        detail={"message": "Invalid 835 data", "errors": [{"type": "missing", "loc": ["raw_835"]}]},
    )


@app.post("/ingest-835")
def ingest_835(
    payload: RemittanceIngest835Request | None = Body(None),
    remittance_file: UploadFile | None = File(None),
    remittance_data: str | None = Form(None),
    db: Session = Depends(get_db),
) -> RemittanceReceivedV1:
    try:
        raw_payload = _extract_remittance_payload(payload, remittance_file, remittance_data)
        parsed_data = _parse_835(raw_payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid 835 data", "errors": exc.errors()},
        ) from exc

    correlation_id = _build_correlation_id(parsed_data)

    record = ProcessingRecord(
        external_id=parsed_data.trace_number,
        amount_cents=sum(c.amount_cents for c in parsed_data.claims),
        raw_payload=raw_payload,
        claims_json=json.dumps([c.model_dump() for c in parsed_data.claims]),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    event = RemittanceReceivedV1(
        correlation_id=correlation_id,
        trace_number=parsed_data.trace_number,
        payer_id=parsed_data.payer_id,
        provider_id=parsed_data.provider_id,
        claims=[
            ClaimReference(claim_id=c.claim_id, amount_cents=c.amount_cents)
            for c in parsed_data.claims
        ],
    )

    publisher.send(
        queue_name=REMITTANCE_RECEIVED_TOPIC,
        message=event.model_dump_json(),
    )

    return event
