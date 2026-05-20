"""Tests for Docker image signing after vulnerability scan gate."""
import pytest
from src.docker.signer import (
    ImageSigner, ScanStatus, ScanReport, VulnerabilityGate,
    ImageSigningError,
)
from src.docker.publish import ImagePublisher, PublishError


def test_sign_requires_scan():
    """Test that signing requires a registered vulnerability scan."""
    signer = ImageSigner()

    with pytest.raises(ImageSigningError, match="No vulnerability scan"):
        signer.sign("sha256:abc123456789", tag="v1.0.0")


def test_sign_blocked_if_scan_pending():
    """Test that signing is blocked while scan is still pending."""
    signer = ImageSigner()
    signer.register_scan(ScanReport(
        image_digest="sha256:def456789abc",
        status=ScanStatus.PENDING,
    ))

    with pytest.raises(ImageSigningError, match="still pending"):
        signer.sign("sha256:def456789abc", tag="v1.0.0")


def test_sign_blocked_if_scan_failed():
    """Test that signing is blocked if scan failed."""
    signer = ImageSigner()
    signer.register_scan(ScanReport(
        image_digest="sha256:abc789def123",
        status=ScanStatus.FAILED,
    ))

    with pytest.raises(ImageSigningError, match="scan failed"):
        signer.sign("sha256:abc789def123", tag="v1.0.0")


def test_sign_blocked_if_gate_fails():
    """Test that signing is blocked if vulnerability count exceeds gate."""
    signer = ImageSigner(gate=VulnerabilityGate(max_critical=0))
    signer.register_scan(ScanReport(
        image_digest="sha256:gatefail123456",
        status=ScanStatus.PASSED,
        findings={"critical": 5, "high": 0, "medium": 0},
    ))

    with pytest.raises(ImageSigningError, match="failed vulnerability gate"):
        signer.sign("sha256:gatefail123456", tag="v1.0.0")


def test_sign_allowed_if_gate_passes():
    """Test that signing is allowed when gate passes."""
    signer = ImageSigner(gate=VulnerabilityGate(max_critical=0, max_high=10))
    signer.register_scan(ScanReport(
        image_digest="sha256:gatespass123456",
        status=ScanStatus.PASSED,
        findings={"critical": 0, "high": 3, "medium": 5},
    ))

    sig = signer.sign("sha256:gatespass123456", tag="v1.0.0")

    assert sig is not None
    assert "signature" in sig
    assert signer.is_signed("sha256:gatespass123456")


def test_publish_fails_without_scan():
    """Test that publish fails if no scan is registered."""
    pub = ImagePublisher()

    with pytest.raises(PublishError, match="No vulnerability scan"):
        pub.publish("sha256:nocan12345678", tag="v1.0.0", registry="ghcr.io/app")


def test_publish_signs_only_after_gate():
    """Test that publish only signs after gate passes."""
    signer = ImageSigner(gate=VulnerabilityGate(max_critical=0))
    pub = ImagePublisher(signer=signer)

    signer.register_scan(ScanReport(
        image_digest="sha256:pubtest12345678",
        status=ScanStatus.PASSED,
        findings={"critical": 1, "high": 0},
    ))

    with pytest.raises(PublishError, match="failed signing gate"):
        pub.publish("sha256:pubtest12345678", tag="v1.0.0", registry="ghcr.io/app")


def test_signature_contains_scan_info():
    """Test that signature includes scan status and findings."""
    signer = ImageSigner()
    signer.register_scan(ScanReport(
        image_digest="sha256:siginfo12345678",
        status=ScanStatus.PASSED,
        findings={"critical": 0, "high": 1, "medium": 2},
    ))

    sig = signer.sign("sha256:siginfo12345678", tag="v1.0.0")

    assert sig["payload"]["scanStatus"] == "passed"
    assert sig["payload"]["scanFindings"] == {"critical": 0, "high": 1, "medium": 2}
    assert sig["payload"]["gate"]["maxCritical"] == 0
