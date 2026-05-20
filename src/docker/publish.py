"""Image publish workflow: gate-based signing before promotion."""

import logging
from typing import Dict, List, Optional

from .signer import ImageSigner, ScanStatus, ScanReport, VulnerabilityGate, ImageSigningError

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Raised when image publish fails."""
    pass


class ImagePublisher:
    """Publishes container images with mandatory scan-gated signing.

    Publish flow:
    1. Validate scan exists for image digest
    2. Wait for scan completion (if pending)
    3. Evaluate gate
    4. Sign only after gate passes
    5. Promote signed image to registry
    """

    def __init__(self, signer: Optional[ImageSigner] = None):
        self.signer = signer or ImageSigner()

    def _wait_for_scan(
        self,
        image_digest: str,
        timeout: int = 300,
        poll_interval: int = 5,
    ) -> ScanReport:
        """Poll for scan completion (simulated)."""
        import time
        scan = self.signer._get_scan(image_digest)
        if scan is None:
            raise PublishError(f"No scan registered for {image_digest[:16]}")

        elapsed = 0
        while scan.status in (ScanStatus.PENDING, ScanStatus.IN_PROGRESS):
            if elapsed >= timeout:
                raise PublishError(
                    f"Scan for {image_digest[:16]} did not complete within {timeout}s"
                )
            logger.info(f"Scan for {image_digest[:16]} still {scan.status.value}, waiting...")
            time.sleep(poll_interval)
            elapsed += poll_interval
            # Re-fetch (in real impl would re-query scanner)
            scan = self.signer._get_scan(image_digest)

        return scan

    def publish(
        self,
        image_digest: str,
        tag: str,
        registry: str,
        signer_id: str = "default",
        wait_for_scan: bool = True,
    ) -> Dict:
        """Publish and sign an image.

        Args:
            image_digest: SHA256 digest of the image
            tag: Image tag (e.g. "v1.2.3")
            registry: Target registry path
            signer_id: Signing key identifier
            wait_for_scan: If True, poll until scan completes

        Returns:
            Dict with signature and promotion status
        """
        full_ref = f"{registry}/{tag}"

        # Step 1: Get scan
        scan = self.signer._get_scan(image_digest)
        if scan is None:
            raise PublishError(
                f"No vulnerability scan found for {image_digest[:16]}. "
                f"Cannot publish unscanned image."
            )

        # Step 2: Wait for scan if needed
        if wait_for_scan and scan.status in (ScanStatus.PENDING, ScanStatus.IN_PROGRESS):
            scan = self._wait_for_scan(image_digest)

        # Step 3: Sign (gate check happens inside)
        try:
            signature = self.signer.sign(image_digest, tag=tag, signer_id=signer_id)
        except ImageSigningError as e:
            logger.error(f"Signing blocked for {image_digest[:16]}: {e}")
            raise PublishError(f"Image failed signing gate: {e}") from e

        # Step 4: Promote to registry (simulated)
        logger.info(f"Promoting signed image {image_digest[:16]} to {full_ref}")

        return {
            "digest": image_digest,
            "tag": tag,
            "registry": registry,
            "ref": full_ref,
            "signed": True,
            "signature_digest": signature["signature"],
            "scan_status": scan.status.value,
            "scan_findings": scan.findings,
            "published_at": scan.scanned_at,
        }
