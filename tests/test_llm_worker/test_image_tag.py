"""Tests for ImageTagHandler."""

import os
import sys
import tempfile
from unittest.mock import AsyncMock

import pytest

# Ensure correct llm_worker path is used - prioritize local version over worktree
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_llm_worker_path = os.path.join(PROJECT_ROOT, "llm_worker")
if _llm_worker_path not in sys.path:
    sys.path.insert(0, _llm_worker_path)

from worker.handlers.image_tag import ImageTagHandler


class TestImageTagHandler:
    """Test cases for ImageTagHandler."""

    @pytest.fixture
    def handler(self, mock_llm_client, mock_core_api, llm_worker_config):
        """Create handler with mocked dependencies."""
        return ImageTagHandler(
            llm_client=mock_llm_client,
            core_api=mock_core_api,
            config=llm_worker_config,
        )

    @pytest.fixture
    def test_image_path(self):
        """Create a small test image file."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            # Write minimal JPEG data (1x1 red pixel)
            f.write(
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00"
                b"\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08"
                b"\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12"
                b"\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x01"
                b"\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00"
                b"\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01"
                b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00"
                b"\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10"
                b"\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01"
                b"\x7d\x01\x02\x03\x00\x04\x05\x06\x07\x08\t\n\x0b\x0c\x10"
                b"\x00\x02\x11\x03\x12\x13\x14\x21\x31\x41\x51\x61\x06"
                b"\x13\x71\x91\xa1\xb1\xc1\x15\xd1\xf0\x24\x32\x81\x91\xa1"
                b"\x01\x00\x03\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00"
                b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08"
                b"\t\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd5\xff\xd9"
            )
            temp_path = f.name
        yield temp_path
        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    async def test_image_tag_success(
        self, handler, mock_llm_client, mock_core_api, test_image_path
    ):
        """Test full happy path with test image."""
        # Mock LLM response
        mock_llm_client.complete_with_image = AsyncMock(
            return_value='{"description": "A cat", "tags": ["cat", "pet"]}'
        )

        # Call handler
        result = await handler.handle(
            job_id="job-123",
            payload={"memory_id": "mem-1", "image_path": test_image_path},
            user_id=12345,
        )

        # Assert result
        assert result == {
            "memory_id": "mem-1",
            "tags": ["cat", "pet"],
            "description": "A cat",
        }

        # Assert core_api.add_tags was called
        mock_core_api.add_tags.assert_called_once_with(
            memory_id="mem-1", tags=["cat", "pet"], status="suggested"
        )

    async def test_image_tag_wrapped_json(self, handler, mock_llm_client):
        """Test parsing JSON wrapped in text."""
        # Mock LLM response with JSON wrapped in text
        mock_llm_client.complete_with_image = AsyncMock(
            return_value='Here are the tags: {"description": "A dog", "tags": ["dog"]} Done.'
        )

        # Call handler with a temp file
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
            temp_path = f.name

        try:
            result = await handler.handle(
                job_id="job-124",
                payload={"memory_id": "mem-2", "image_path": temp_path},
                user_id=12345,
            )

            # Assert result parses correctly
            assert result == {
                "memory_id": "mem-2",
                "tags": ["dog"],
                "description": "A dog",
            }
        finally:
            os.unlink(temp_path)

    async def test_image_tag_empty_tags(self, handler, mock_llm_client, mock_core_api):
        """Test when no tags returned - add_tags should not be called."""
        # Mock LLM response with empty tags
        mock_llm_client.complete_with_image = AsyncMock(
            return_value='{"description": "Unclear image", "tags": []}'
        )

        # Create temp file
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
            temp_path = f.name

        try:
            result = await handler.handle(
                job_id="job-125",
                payload={"memory_id": "mem-3", "image_path": temp_path},
                user_id=12345,
            )

            # Assert result has empty tags list
            assert result == {
                "memory_id": "mem-3",
                "tags": [],
                "description": "Unclear image",
            }

            # Assert core_api.add_tags was NOT called (no tags to add)
            mock_core_api.add_tags.assert_not_called()
        finally:
            os.unlink(temp_path)

    async def test_image_tag_file_not_found(self, handler):
        """Test non-existent image path raises FileNotFoundError."""
        non_existent_path = "/tmp/this_file_does_not_exist.jpg"

        with pytest.raises(FileNotFoundError):
            await handler.handle(
                job_id="job-126",
                payload={"memory_id": "mem-4", "image_path": non_existent_path},
                user_id=12345,
            )
