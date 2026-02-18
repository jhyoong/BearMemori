"""Custom PTB filters for Telegram Gateway."""

from telegram import Update
from telegram.ext import filters


class AllowedUsersFilter(filters.UpdateFilter):
    """Filter that only passes updates from allowlisted users.

    This filter checks if the user who sent the message or callback query
    is in the allowed set of user IDs.
    """

    def __init__(self, allowed_ids: set[int]) -> None:
        """Initialize the filter with a set of allowed user IDs.

        Args:
            allowed_ids: Set of user IDs that are allowed to use the bot.
        """
        super().__init__()
        self.allowed_ids = allowed_ids

    def filter(self, update: Update) -> bool:
        """Check if the update is from an allowed user.

        Args:
            update: The Telegram update to check.

        Returns:
            True if the user is in the allowed set, False otherwise.
            Also returns False if the update has no user (e.g., channel posts).
        """
        # Check for user in message
        if update.message and update.message.from_user:
            user_id = update.message.from_user.id
            return user_id in self.allowed_ids

        # Check for user in callback query
        if update.callback_query and update.callback_query.from_user:
            user_id = update.callback_query.from_user.id
            return user_id in self.allowed_ids

        # Check for user in edited message
        if update.edited_message and update.edited_message.from_user:
            user_id = update.edited_message.from_user.id
            return user_id in self.allowed_ids

        # Check for user in channel post
        if update.channel_post and update.channel_post.from_user:
            user_id = update.channel_post.from_user.id
            return user_id in self.allowed_ids

        # Check for user in edited channel post
        if update.edited_channel_post and update.edited_channel_post.from_user:
            user_id = update.edited_channel_post.from_user.id
            return user_id in self.allowed_ids

        # No user found in the update - deny access
        return False
