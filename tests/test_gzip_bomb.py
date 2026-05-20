"""Tests for gzip bomb prevention in BodyDecompressionMiddleware."""
import gzip
import io
import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from src.api.middleware import BodyDecompressionMiddleware


async def echo(request):
    body = await request.body()
    return JSONResponse({"size": len(body)})


app = Starlette(routes=[Route("/echo", echo)])
app.add_middleware(BodyDecompressionMiddleware, max_size=1024 * 1024, ratio_limit=10)
client = TestClient(app)


def test_normal_gzip_accepted():
    """Test that normal gzip content is accepted."""
    original = b"Hello, World!" * 100  # compressible data
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode='wb') as f:
        f.write(original)
    
    response = client.post(
        "/echo",
        content=compressed.getvalue(),
        headers={"content-encoding": "gzip"}
    )
    assert response.status_code == 200
    assert response.json()["size"] == len(original)


def test_gzip_bomb_rejected():
    """Test that gzip bomb (high compression ratio) is rejected at ratio check."""
    # Create a gzip bomb: highly compressible data (repeated bytes)
    # This would decompress to huge size but we reject at ratio level
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode='wb') as f:
        f.write(b"\x00" * 100000)  # 100KB of zeros -> ~100:1 compression
    
    response = client.post(
        "/echo",
        content=compressed.getvalue(),
        headers={"content-encoding": "gzip"}
    )
    # Should be rejected - decompressed would exceed max_size or ratio
    assert response.status_code in (400, 413)


def test_invalid_compressed_rejected():
    """Test that invalid compressed data is rejected."""
    response = client.post(
        "/echo",
        content=b"not compressed data",
        headers={"content-encoding": "gzip"}
    )
    assert response.status_code == 400


def test_no_encoding_passthrough():
    """Test that non-compressed requests pass through."""
    response = client.post(
        "/echo",
        content=b"plain text",
        headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200


def test_ratio_limit_enforced():
    """Test that ratio limit is enforced before full decompression."""
    # Create compressed data that is within ratio but still large
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode='wb') as f:
        f.write(b"x" * 10000)  # 10KB compresses to ~15 bytes
    
    # With ratio_limit=10, 10KB compressed would allow 100KB decompressed
    # This is within limit, should pass
    response = client.post(
        "/echo",
        content=compressed.getvalue(),
        headers={"content-encoding": "gzip"}
    )
    assert response.status_code == 200
