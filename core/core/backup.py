"""S3 backup module stub for Phase 1."""

import logging

logger = logging.getLogger(__name__)


async def run_backup(db_path: str, image_dir: str, s3_bucket: str, s3_region: str) -> None:
    """S3 backup is not configured in Phase 1. This is a stub."""
    logger.info("S3 backup not configured -- skipping")
