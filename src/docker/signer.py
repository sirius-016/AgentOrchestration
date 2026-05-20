"""Docker image signing with mandatory vulnerability scan gate.

Signing occurs ONLY after vulnerability scan completes and passes the approval threshold.
This prevents consumers from trusting signatures on images that did not pass the gate.
"""

import hashlib
import json
import logging
import time
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ScanStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    NOT_FOUND = "not_found"


class ImageSigningError(Exception):
    """Raised when image signing fails."""
    pass


class VulnerabilityGate:
    """Configuration for the vulnerability scan gate.

    An image can only be signed if its vulnerability scan meets these criteria.
    """

    def __init__(
        self,
        max_critical: int = 0,
        max_high: int = 5,
        max_medium: int = 20,
        block_on_unscanned: bool = True,
    ):
        self.max_critical = max_critical
        self.max_high = max_high
        self.max_medium = max_medium
        self.block_on_unscanned = block_on_unscanned

    def evaluate(self, scan_report: Dict) -> tuple[bool, List[str]]:
        """Evaluate a scan report against the gate criteria.

        Returns (passed, violations).
        """
        violations = []
        findings = scan_report.get("findings", {})

        critical = findings.get("critical", 0)
        if critical > self.max_critical:
            violations.append(
                f"Critical vulnerabilities {critical} > limit {self.max_critical}"
            )

        high = findings.get("high", 0)
        if high > self.max_high:
            violations.append(
                f"High vulnerabilities {high} > limit {self.max_high}"
            )

        medium = findings.get("medium", 0)
        if medium > self.max_medium:
            violations.append(
                f"Medium vulnerabilities {medium} > limit {self.max_medium}"
            )

        return len(violations) == 0, violations


class ScanReport:
    """Represents a vulnerability scan report for a container image digest."""

    def __init__(
        self,
        image_digest: str,
        status: ScanStatus,
        findings: Optional[Dict[str, int]] = None,
        scanned_at: Optional[float] = None,
        scanner_version: str = "",
    ):
        self.image_digest = image_digest
        self.status = status
        self.findings = findings or {}
        self.scanned_at = scanned_at or time.time()
        self.scanner_version = scanner_version

    def to_dict(self) -> Dict:
        return {
            "image_digest": self.image_digest,
            "status": self.status.value,
            "findings": self.findings,
            "scanned_at": self.scanned_at,
            "scanner_version": self.scanner_version,
        }


class ImageSigner:
    """Signs container images only after vulnerability scan gate approval.

    The signing workflow:
    1. Image is built and pushed with a digest
    2. Vulnerability scan is triggered for that digest
    3. ImageSigner waits for scan to complete
    4. Gate is evaluated against scan results
    5. Signing proceeds ONLY if gate passes
    """

    # Signatures are stored here (replace with a real trust store in production)
    _signatures: Dict[str, Dict] = {}

    def __init__(self, gate: Optional[VulnerabilityGate] = None):
        self.gate = gate or VulnerabilityGate()
        self._scan_cache: Dict[str, ScanReport] = {}

    def register_scan(self, report: ScanReport) -> None:
        """Register a vulnerability scan result for an image digest."""
        if report.image_digest in self._scan_cache:
            logger.warning(f"Scan already registered for {report.image_digest[:16]}, overwriting")
        self._scan_cache[report.image_digest] = report
        logger.info(
            f"Registered scan: digest={report.image_digest[:16]}, "
            f"status={report.status.value}, findings={report.findings}"
        )

    def _get_scan(self, image_digest: str) -> Optional[ScanReport]:
        """Get the scan report for an image digest."""
        return self._scan_cache.get(image_digest)

    def sign(self, image_digest: str, tag: str, signer_id: str = "default") -> Dict:
        """Sign a container image digest.

        Signing is ONLY allowed if:
        1. A vulnerability scan exists for this digest
        2. The scan status is PASSED
        3. The gate evaluation passes

        Args:
            image_digest: The SHA256 digest of the image (e.g. "sha256:abc123...")
            tag: The image tag used for reference
            signer_id: Identifier for the signing key used

        Returns:
            Signature metadata dict

        Raises:
            ImageSigningError: If signing fails any gate check
        """
        # Step 1: Check scan exists
        scan = self._get_scan(image_digest)
        if scan is None:
            raise ImageSigningError(
                f"No vulnerability scan found for digest {image_digest[:16]}. "
                f"Cannot sign unscanned image."
            )

        # Step 2: Check scan status
        if scan.status == ScanStatus.NOT_FOUND:
            raise ImageSigningError(
                f"Image digest {image_digest[:16]} was not found by scanner. "
                f"Cannot sign unscanned image."
            )

        if scan.status == ScanStatus.PENDING or scan.status == ScanStatus.IN_PROGRESS:
            raise ImageSigningError(
                f"Vulnerability scan for {image_digest[:16]} is still {scan.status.value}. "
                f"Cannot sign until scan completes."
            )

        if scan.status == ScanStatus.FAILED:
            raise ImageSigningError(
                f"Vulnerability scan for {image_digest[:16]} failed. "
                f"Cannot sign unscanned image."
            )

        # Step 3: Evaluate gate
        gate_passed, violations = self.gate.evaluate(scan.to_dict())
        if not gate_passed:
            raise ImageSigningError(
                f"Image digest {image_digest[:16]} failed vulnerability gate: "
                + "; ".join(violations)
            )

        # Step 4: Sign the image (simulated - use cosign/syft in production)
        signature_payload = {
            "imageDigest": image_digest,
            "tag": tag,
            "signer": signer_id,
            "signedAt": time.time(),
            "scanStatus": scan.status.value,
            "scanFindings": scan.findings,
            "gate": {
                "maxCritical": self.gate.max_critical,
                "maxHigh": self.gate.max_high,
                "maxMedium": self.gate.max_medium,
            },
        }

        sig_hash = hashlib.sha256(
            json.dumps(signature_payload, sort_keys=True).encode()
        ).hexdigest()

        signature = {
            "payload": signature_payload,
            "signature": sig_hash,
            "version": "1.0",
        }

        ImageSigner._signatures[image_digest] = signature
        logger.info(
            f"Signed image {image_digest[:16]} (tag={tag}, "
            f"scan_passed=True, signer={signer_id})"
        )

        return signature

    def verify(self, image_digest: str) -> Optional[Dict]:
        """Verify a signature for an image digest.

        Returns signature metadata if valid, None if not found.
        """
        return ImageSigner._signatures.get(image_digest)

    def is_signed(self, image_digest: str) -> bool:
        """Check if an image digest has been signed."""
        return image_digest in ImageSigner._signatures
