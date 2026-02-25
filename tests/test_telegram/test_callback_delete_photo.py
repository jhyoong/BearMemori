"""Tests for handle_memory_action with photo messages in confirm_delete action."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.callback import handle_memory_action, handle_confirm_delete
from tg_gateway.callback_data import MemoryAction


class TestHandleMemoryActionConfirmDeletePhoto:
    """Tests for handle_memory_action with confirm_delete action and photo messages."""

    @pytest.fixture
    def mock_update_text(self):
        """Create a mock update for text message (no photo)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        # Text message - photo is None
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = None
        update.callback_query.edit_message_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_update_with_photo(self):
        """Create a mock update for image message (has photo)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        # Image message - photo is a list (list of PhotoSize objects)
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = [MagicMock(), MagicMock()]  # Has photo
        update.callback_query.edit_message_caption = AsyncMock()
        # Also add edit_message_text to track if it gets called incorrectly
        update.callback_query.edit_message_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        return context

    @pytest.fixture
    def mock_core_client(self):
        """Create a mock core client."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_confirm_delete_text_message_uses_edit_message_text(
        self, mock_update_text, mock_context, mock_core_client
    ):
        """Test confirm_delete action on text message calls edit_message_text.

        When the memory is a text message (photo=None), the function should
        call edit_message_text to show the confirmation keyboard.
        """
        callback_data = MemoryAction(action="confirm_delete", memory_id="123")

        await handle_memory_action(
            mock_update_text, mock_context, callback_data, mock_core_client
        )

        # For text message, should use edit_message_text
        mock_update_text.callback_query.edit_message_text.assert_called_once()

        # Verify the message text and keyboard are passed
        call_args = mock_update_text.callback_query.edit_message_text.call_args
        assert "Are you sure you want to delete this memory?" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_confirm_delete_photo_message_uses_edit_message_caption(
        self, mock_update_with_photo, mock_context, mock_core_client
    ):
        """Test confirm_delete action on photo message calls edit_message_caption.

        When the memory has a photo attached (photo is not None), the function should
        call edit_message_caption to show the confirmation keyboard.
        This test MUST FAIL until the fix is implemented.
        """
        callback_data = MemoryAction(action="confirm_delete", memory_id="123")

        await handle_memory_action(
            mock_update_with_photo, mock_context, callback_data, mock_core_client
        )

        # For photo message, should use edit_message_caption
        mock_update_with_photo.callback_query.edit_message_caption.assert_called_once()

        # Verify the message text and keyboard are passed
        call_args = mock_update_with_photo.callback_query.edit_message_caption.call_args
        assert "Are you sure you want to delete this memory?" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_confirm_delete_photo_message_detects_photo_correctly(
        self, mock_update_with_photo, mock_context, mock_core_client
    ):
        """Test that the function correctly detects photo via callback_query.message.photo.

        The function should check if callback_query.message.photo is not None
        to determine if it's a photo message.
        """
        callback_data = MemoryAction(action="confirm_delete", memory_id="123")

        # Verify our mock has the correct setup
        assert mock_update_with_photo.callback_query.message.photo is not None

        await handle_memory_action(
            mock_update_with_photo, mock_context, callback_data, mock_core_client
        )

        # The function should detect photo is not None and call edit_message_caption
        mock_update_with_photo.callback_query.edit_message_caption.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_delete_photo_message_does_not_call_edit_message_text(
        self, mock_update_with_photo, mock_context, mock_core_client
    ):
        """Test that confirm_delete with photo does NOT call edit_message_text.

        For photo messages, the function should NOT use edit_message_text.
        This test MUST FAIL until the fix is implemented.
        """
        callback_data = MemoryAction(action="confirm_delete", memory_id="123")

        await handle_memory_action(
            mock_update_with_photo, mock_context, callback_data, mock_core_client
        )

        # For photo message, should NOT use edit_message_text
        mock_update_with_photo.callback_query.edit_message_text.assert_not_called()


# =============================================================================
# Tests for handle_confirm_delete with confirmed=False (cancel delete flow)
# =============================================================================


class TestHandleConfirmDeleteCancelPhoto:
    """Tests for handle_confirm_delete with confirmed=False and photo messages."""

    @pytest.fixture
    def mock_update_text_message(self):
        """Create a mock update for text message (no photo)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        # Text message - photo is None
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = None
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()
        return update

    @pytest.fixture
    def mock_update_photo_message(self):
        """Create a mock update for image message (has photo)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        # Image message - photo is a list (list of PhotoSize objects)
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = [MagicMock(), MagicMock()]  # Has photo
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        return context

    @pytest.fixture
    def mock_core_client_text_memory(self):
        """Create a mock core client returning a text memory."""
        client = MagicMock()
        # Memory without image
        client.get_memory = AsyncMock(
            return_value=MagicMock(
                memory_id="123",
                content="Test memory content",
                media_type="text",
                media_file_id=None,
            )
        )
        client.delete_memory = AsyncMock()
        return client

    @pytest.fixture
    def mock_core_client_photo_memory(self):
        """Create a mock core client returning a photo memory."""
        client = MagicMock()
        # Memory with image
        client.get_memory = AsyncMock(
            return_value=MagicMock(
                memory_id="123",
                content="Test memory with photo",
                media_type="image",
                media_file_id="file_123_photo",
            )
        )
        client.delete_memory = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_cancel_delete_text_message_uses_edit_message_text(
        self, mock_update_text_message, mock_context, mock_core_client_text_memory
    ):
        """Test handle_confirm_delete with confirmed=False and text message.

        When the user cancels delete (confirmed=False) on a text memory,
        the function should call edit_message_text to restore the original keyboard.
        """
        from tg_gateway.callback_data import ConfirmDelete

        callback_data = ConfirmDelete(memory_id="123", confirmed=False)

        await handle_confirm_delete(
            mock_update_text_message,
            mock_context,
            callback_data,
            mock_core_client_text_memory,
        )

        # For text message, should use edit_message_text
        mock_update_text_message.callback_query.edit_message_text.assert_called_once()

        # Verify the message text is passed
        call_args = mock_update_text_message.callback_query.edit_message_text.call_args
        assert "Test memory content" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cancel_delete_photo_message_uses_edit_message_caption(
        self, mock_update_photo_message, mock_context, mock_core_client_photo_memory
    ):
        """Test handle_confirm_delete with confirmed=False and photo message.

        When the user cancels delete (confirmed=False) on a photo memory,
        the function should call edit_message_caption to restore the original keyboard.
        This test MUST FAIL until the fix is implemented.
        """
        from tg_gateway.callback_data import ConfirmDelete

        callback_data = ConfirmDelete(memory_id="123", confirmed=False)

        await handle_confirm_delete(
            mock_update_photo_message,
            mock_context,
            callback_data,
            mock_core_client_photo_memory,
        )

        # For photo message, should use edit_message_caption
        mock_update_photo_message.callback_query.edit_message_caption.assert_called_once()

        # Verify the message text is passed
        call_args = (
            mock_update_photo_message.callback_query.edit_message_caption.call_args
        )
        assert "Test memory with photo" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_cancel_delete_photo_message_does_not_call_edit_message_text(
        self, mock_update_photo_message, mock_context, mock_core_client_photo_memory
    ):
        """Test that cancel delete with photo does NOT call edit_message_text.

        For photo messages, the function should use edit_message_caption,
        not edit_message_text. This test MUST FAIL until the fix is implemented.
        """
        from tg_gateway.callback_data import ConfirmDelete

        callback_data = ConfirmDelete(memory_id="123", confirmed=False)

        await handle_confirm_delete(
            mock_update_photo_message,
            mock_context,
            callback_data,
            mock_core_client_photo_memory,
        )

        # For photo message, should NOT use edit_message_text
        mock_update_photo_message.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_delete_photo_message_checks_message_photo_attribute(
        self, mock_update_photo_message, mock_context, mock_core_client_photo_memory
    ):
        """Test that the function correctly detects photo via callback_query.message.photo.

        When confirmed=False and the original message has a photo (photo is not None),
        the function should use edit_message_caption to restore the keyboard.
        This test MUST FAIL until the fix is implemented.
        """
        from tg_gateway.callback_data import ConfirmDelete

        # Verify our mock has the correct setup - photo is not None
        assert mock_update_photo_message.callback_query.message.photo is not None

        callback_data = ConfirmDelete(memory_id="123", confirmed=False)

        await handle_confirm_delete(
            mock_update_photo_message,
            mock_context,
            callback_data,
            mock_core_client_photo_memory,
        )

        # The function should detect photo is not None and call edit_message_caption
        mock_update_photo_message.callback_query.edit_message_caption.assert_called_once()


# =============================================================================
# Tests for handle_confirm_delete with confirmed=True (actual delete)
# =============================================================================


class TestHandleConfirmDeletePhoto:
    """Tests for handle_confirm_delete with confirmed=True and photo messages."""

    @pytest.fixture
    def mock_update_text_message(self):
        """Create a mock update for text message (no photo)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        # Text message - photo is None
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = None
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()
        return update

    @pytest.fixture
    def mock_update_photo_message(self):
        """Create a mock update for image message (has photo)."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        # Image message - photo is a list (list of PhotoSize objects)
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = [MagicMock(), MagicMock()]  # Has photo
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        return context

    @pytest.fixture
    def mock_core_client(self):
        """Create a mock core client."""
        client = MagicMock()
        client.delete_memory = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_confirm_delete_text_message_uses_edit_message_text(
        self, mock_update_text_message, mock_context, mock_core_client
    ):
        """Test handle_confirm_delete with confirmed=True and text message.

        When confirmed=True on a text memory, the function should
        call edit_message_text with "Memory deleted".
        """
        from tg_gateway.callback_data import ConfirmDelete

        callback_data = ConfirmDelete(memory_id="123", confirmed=True)

        await handle_confirm_delete(
            mock_update_text_message,
            mock_context,
            callback_data,
            mock_core_client,
        )

        # For text message, should use edit_message_text with "Memory deleted"
        mock_update_text_message.callback_query.edit_message_text.assert_called_once()

        # Verify the message text contains "Memory deleted"
        call_args = mock_update_text_message.callback_query.edit_message_text.call_args
        assert "Memory deleted" in call_args[0][0]

        # Should have called delete_memory
        mock_core_client.delete_memory.assert_called_once_with("123")

    @pytest.mark.asyncio
    async def test_confirm_delete_photo_message_uses_edit_message_caption(
        self, mock_update_photo_message, mock_context, mock_core_client
    ):
        """Test handle_confirm_delete with confirmed=True and photo message.

        When confirmed=True on a photo memory, the function should
        call edit_message_caption with "Memory deleted" text.
        This test MUST FAIL until the fix is implemented.
        """
        from tg_gateway.callback_data import ConfirmDelete

        callback_data = ConfirmDelete(memory_id="123", confirmed=True)

        await handle_confirm_delete(
            mock_update_photo_message,
            mock_context,
            callback_data,
            mock_core_client,
        )

        # For photo message, should use edit_message_caption
        mock_update_photo_message.callback_query.edit_message_caption.assert_called_once()

        # Verify the message text contains "Memory deleted"
        call_args = (
            mock_update_photo_message.callback_query.edit_message_caption.call_args
        )
        assert "Memory deleted" in call_args[0][0]

        # Should have called delete_memory
        mock_core_client.delete_memory.assert_called_once_with("123")

    @pytest.mark.asyncio
    async def test_confirm_delete_photo_message_does_not_call_edit_message_text(
        self, mock_update_photo_message, mock_context, mock_core_client
    ):
        """Test that confirm delete with photo does NOT call edit_message_text.

        For photo messages when confirmed=True, the function should use
        edit_message_caption, not edit_message_text.
        This test MUST FAIL until the fix is implemented.
        """
        from tg_gateway.callback_data import ConfirmDelete

        callback_data = ConfirmDelete(memory_id="123", confirmed=True)

        await handle_confirm_delete(
            mock_update_photo_message,
            mock_context,
            callback_data,
            mock_core_client,
        )

        # For photo message, should NOT use edit_message_text
        mock_update_photo_message.callback_query.edit_message_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_delete_photo_message_checks_message_photo_attribute(
        self, mock_update_photo_message, mock_context, mock_core_client
    ):
        """Test that the function correctly detects photo via callback_query.message.photo.

        When confirmed=True and the message has a photo (photo is not None),
        the function should use edit_message_caption to show "Memory deleted".
        This test MUST FAIL until the fix is implemented.
        """
        from tg_gateway.callback_data import ConfirmDelete

        # Verify our mock has the correct setup - photo is not None
        assert mock_update_photo_message.callback_query.message.photo is not None

        callback_data = ConfirmDelete(memory_id="123", confirmed=True)

        await handle_confirm_delete(
            mock_update_photo_message,
            mock_context,
            callback_data,
            mock_core_client,
        )

        # The function should detect photo is not None and call edit_message_caption
        mock_update_photo_message.callback_query.edit_message_caption.assert_called_once()
