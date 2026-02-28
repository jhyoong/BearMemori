"""Media handling utilities for the Telegram Gateway.

This module provides functions for downloading images from Telegram and
uploading them to Core.
"""

import logging

logger = logging.getLogger(__name__)


async def download_and_upload_image(
    bot, core_client, memory_id: str, file_id: str
) -> str | None:
    """Download an image from Telegram and upload it to Core.

    Args:
        bot: The Telegram bot instance.
        core_client: The Core API client.
        memory_id: The ID of the memory to attach the image to.
        file_id: The Telegram file_id of the image.

    Returns:
        The local path returned by Core on success, None on failure.
    """
    try:
        # Download from Telegram
        tg_file = await bot.get_file(file_id)
        file_bytes = await tg_file.download_as_bytearray()

        # Upload to Core
        local_path = await core_client.upload_image(memory_id, bytes(file_bytes))
        logger.info(f"Successfully uploaded image for memory {memory_id}")
        return local_path
    except Exception:
        logger.exception(f"Failed to download/upload image for memory {memory_id}")
        return None
