"""Real synthetic HEIC bytes enter the ordinary route without replacing camera evidence."""

import hashlib
import json
from pathlib import Path

from exulanica.corpus.decode import open_sensor
from exulanica.evidence.blob import BlobId
from exulanica.ingest.decode import open_upright
from exulanica.reconstruction.source_lineage import verify_decoded_record

from test_intake_upload import upload as upload

FIXTURE = Path(__file__).parent / "fixtures/personal-heic/single-frame.heic"


def test_heic_intake_records_derivative_and_preserves_original_evidence(upload):
    data = FIXTURE.read_bytes()
    response = upload.one(data, name="camera.heic", media="image/heic")
    assert response.status_code == 202 and response.json()["refused"] == [], response.text
    accepted = response.json()["accepted"][0]
    assert accepted["blob_sha256"] == hashlib.sha256(data).hexdigest()
    [row] = upload.rows("select * from decoded_source")
    record = row["receipt_record"]
    output = bytes(row["output_sha256"])
    verify_decoded_record(record, source_sha256=accepted["blob_sha256"], output_sha256=output.hex())
    assert record["decoder"]["pi-heif"] == "1.4.0"
    decoded = upload.store.get(BlobId(output))
    assert decoded.startswith(b"\x89PNG")
    source_image, _ = open_upright(data)
    with open_sensor(decoded) as pixels:
        assert pixels.size == source_image.size == (64, 48)
        assert pixels.tobytes() == source_image.convert("RGB").tobytes()
        assert pixels.getexif().get(274, 1) == 1
    [span] = upload.rows("select span_id from evidence_span where region is null")
    original = upload.get(f"/evidence/{span['span_id']}")
    assert original.status_code == 200 and original.content == data
    viewed = upload.get(f"/evidence/{span['span_id']}/masked")
    assert viewed.status_code == 200 and viewed.content == decoded, viewed.text
    assert viewed.headers["content-type"] == "image/png"
    assert viewed.headers["x-exulanica-view-kind"] == "decoded"
    before = upload.rows(
        "select artifact_id,idempotency_key,content_sha256 from artifact order by artifact_id"
    )
    again = upload.one(data, name="renamed.heif", media="image/heif")
    assert again.json()["accepted"][0]["capture_id"] == accepted["capture_id"]
    assert (
        upload.rows(
            "select artifact_id,idempotency_key,content_sha256 from artifact order by artifact_id"
        )
        == before
    )
    assert len(upload.rows("select * from decoded_source")) == 1
    graph = upload.get("/graph").json()
    serialized = json.dumps(graph)
    assert output.hex() in serialized and "image/png" in serialized
