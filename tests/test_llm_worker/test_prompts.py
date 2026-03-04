"""Tests for LLM Worker prompt templates."""

import os
import sys


# Ensure correct llm_worker path is used - prioritize local version over worktree
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_llm_worker_path = os.path.join(PROJECT_ROOT, "llm_worker")
if _llm_worker_path not in sys.path:
    sys.path.insert(0, _llm_worker_path)

from worker.prompts import INTENT_CLASSIFY_PROMPT, RECLASSIFY_PROMPT


class TestIntentClassifyPrompt:
    """Test cases for INTENT_CLASSIFY_PROMPT template."""

    def test_prompt_contains_all_five_intent_categories(self):
        """Test that prompt includes all required intent categories."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Check for all 5 required intent categories
        assert "reminder" in prompt_text, "Prompt should include 'reminder' intent"
        assert "task" in prompt_text, "Prompt should include 'task' intent"
        assert "search" in prompt_text, "Prompt should include 'search' intent"
        assert "general_note" in prompt_text, (
            "Prompt should include 'general_note' intent"
        )
        assert "ambiguous" in prompt_text, "Prompt should include 'ambiguous' intent"

    def test_prompt_accepts_message_variable(self):
        """Test that prompt uses {message} variable instead of {query}."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # The prompt should accept {message} not {query}
        assert "{message}" in prompt_text, "Prompt should use {message} variable"

    def test_prompt_accepts_original_timestamp_variable(self):
        """Test that prompt accepts {original_timestamp} variable."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        assert "{original_timestamp}" in prompt_text, (
            "Prompt should accept {original_timestamp}"
        )

    def test_prompt_extracts_reminder_entities(self):
        """Test that prompt includes entity extraction for reminder intent."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Check for reminder-specific entity fields
        assert "action" in prompt_text.lower(), "Reminder should extract 'action'"
        assert "time" in prompt_text.lower(), "Reminder should extract 'time'"
        assert "resolved_time" in prompt_text, (
            "Reminder should include resolved_time field"
        )

    def test_prompt_extracts_task_entities(self):
        """Test that prompt includes entity extraction for task intent."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Check for task-specific entity fields
        assert "description" in prompt_text.lower(), "Task should extract 'description'"
        assert "due_time" in prompt_text.lower(), "Task should extract 'due_time'"
        assert "resolved_due_time" in prompt_text, (
            "Task should include resolved_due_time field"
        )

    def test_prompt_extracts_search_entities(self):
        """Test that prompt includes entity extraction for search intent."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Check for search-specific entity fields
        assert "query" in prompt_text.lower(), "Search should extract 'query'"
        assert "keywords" in prompt_text.lower(), "Search should extract 'keywords'"

    def test_prompt_extracts_general_note_entities(self):
        """Test that prompt includes entity extraction for general_note intent."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Check for general_note-specific entity fields
        assert "suggested_tags" in prompt_text.lower(), (
            "general_note should extract 'suggested_tags'"
        )

    def test_prompt_extracts_ambiguous_entities(self):
        """Test that prompt includes entity extraction for ambiguous intent."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Check for ambiguous-specific entity fields
        assert "followup_question" in prompt_text.lower(), (
            "ambiguous should extract 'followup_question'"
        )
        assert "possible_intents" in prompt_text.lower(), (
            "ambiguous should extract 'possible_intents'"
        )

    def test_prompt_includes_iso8601_resolution(self):
        """Test that prompt instructs to resolve relative times to ISO8601."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # The prompt should mention ISO 8601 format for resolved times
        assert "ISO" in prompt_text or "iso" in prompt_text, (
            "Prompt should mention ISO8601"
        )

    def test_prompt_formats_with_given_variables(self):
        """Test that the prompt can be formatted with message and original_timestamp."""
        test_message = "Remind me to buy groceries tomorrow at 5pm"
        test_timestamp = "2024-01-15T10:00:00Z"

        # This should not raise an exception
        formatted = INTENT_CLASSIFY_PROMPT.format(
            message=test_message,
            original_timestamp=test_timestamp,
            user_timezone="America/New_York",
        )

        # Verify the variables are substituted
        assert test_message in formatted, "message should be substituted into prompt"
        assert test_timestamp in formatted, (
            "original_timestamp should be substituted into prompt"
        )

    def test_prompt_returns_json_format_instruction(self):
        """Test that prompt instructs to return JSON format."""
        prompt_text = INTENT_CLASSIFY_PROMPT

        # Should instruct to return JSON
        assert "JSON" in prompt_text, "Prompt should mention JSON format"


class TestReclassifyPrompt:
    """Test cases for RECLASSIFY_PROMPT template."""

    def test_reclassify_prompt_exists(self):
        """Test that RECLASSIFY_PROMPT is defined."""
        assert RECLASSIFY_PROMPT is not None, "RECLASSIFY_PROMPT should be defined"

    def test_reclassify_prompt_accepts_original_message(self):
        """Test that prompt accepts {original_message} variable."""
        prompt_text = RECLASSIFY_PROMPT

        assert "{original_message}" in prompt_text, (
            "RECLASSIFY_PROMPT should accept {original_message}"
        )

    def test_reclassify_prompt_accepts_followup_question(self):
        """Test that prompt accepts {followup_question} variable."""
        prompt_text = RECLASSIFY_PROMPT

        assert "{followup_question}" in prompt_text, (
            "RECLASSIFY_PROMPT should accept {followup_question}"
        )

    def test_reclassify_prompt_accepts_user_answer(self):
        """Test that prompt accepts {user_answer} variable."""
        prompt_text = RECLASSIFY_PROMPT

        assert "{user_answer}" in prompt_text, (
            "RECLASSIFY_PROMPT should accept {user_answer}"
        )

    def test_reclassify_prompt_accepts_original_timestamp(self):
        """Test that prompt accepts {original_timestamp} variable."""
        prompt_text = RECLASSIFY_PROMPT

        assert "{original_timestamp}" in prompt_text, (
            "RECLASSIFY_PROMPT should accept {original_timestamp}"
        )

    def test_reclassify_prompt_formats_with_all_variables(self):
        """Test that the prompt can be formatted with all required variables."""
        original_message = "Remind me to call John"
        followup_question = "When exactly do you want to be reminded?"
        user_answer = "Tomorrow at 3pm"
        original_timestamp = "2024-01-15T10:00:00Z"

        # This should not raise an exception
        formatted = RECLASSIFY_PROMPT.format(
            original_message=original_message,
            followup_question=followup_question,
            user_answer=user_answer,
            original_timestamp=original_timestamp,
            user_timezone="UTC",
        )

        # Verify all variables are substituted
        assert original_message in formatted
        assert followup_question in formatted
        assert user_answer in formatted
        assert original_timestamp in formatted

    def test_reclassify_prompt_returns_json_format(self):
        """Test that prompt instructs to return structured JSON."""
        prompt_text = RECLASSIFY_PROMPT

        # Should instruct to return JSON
        assert "JSON" in prompt_text, "RECLASSIFY_PROMPT should mention JSON format"

    def test_reclassify_prompt_uses_same_intent_categories(self):
        """Test that reclassification uses same intent categories as primary classification."""
        reclassify_text = RECLASSIFY_PROMPT
        classify_text = INTENT_CLASSIFY_PROMPT

        # Both should reference the same intent categories
        # Check that reminder is in both
        assert "reminder" in reclassify_text and "reminder" in classify_text

    def test_reclassify_prompt_contains_critical_timezone_instruction(self):
        """Test that prompt contains CRITICAL instruction about timezone conversion."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should contain explicit CRITICAL instruction about timezone
        assert "CRITICAL" in prompt_text, (
            "RECLASSIFY_PROMPT should contain CRITICAL instruction about timezone"
        )
        assert "timezone" in prompt_text.lower(), (
            "RECLASSIFY_PROMPT should mention timezone"
        )

    def test_reclassify_prompt_contains_convert_to_utc_instruction(self):
        """Test that prompt contains explicit 'convert to UTC' instruction."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should explicitly instruct to convert times to UTC
        assert (
            "convert to UTC" in prompt_text.lower()
            or "convert to utc" in prompt_text.lower()
        ), (
            "RECLASSIFY_PROMPT should explicitly instruct to convert time references to UTC"
        )

    def test_reclassify_prompt_contains_user_timezone_variable(self):
        """Test that prompt template accepts {user_timezone} variable."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should use {user_timezone} placeholder
        assert "{user_timezone}" in prompt_text, (
            "RECLASSIFY_PROMPT should accept {user_timezone} variable"
        )

    def test_reclassify_prompt_renders_with_timezone_value(self):
        """Test that prompt can be formatted with user_timezone and the value is substituted."""
        test_timezone = "Asia/Singapore"

        # Format the prompt with the timezone
        formatted = RECLASSIFY_PROMPT.format(
            original_message="Remind me to call John",
            followup_question="When exactly do you want to be reminded?",
            user_answer="5pm",
            original_timestamp="2026-03-04T10:00:00Z",
            user_timezone=test_timezone,
        )

        # Verify the timezone value is substituted into the prompt
        assert test_timezone in formatted, (
            "user_timezone value should be substituted into the rendered prompt"
        )

    def test_reclassify_prompt_instructs_to_use_timezone_for_time_conversion(self):
        """Test that prompt instructs LLM to use user_timezone for converting time references."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should instruct to use the provided user_timezone for time conversion
        assert (
            "use" in prompt_text.lower() and "user_timezone" in prompt_text.lower()
        ), "RECLASSIFY_PROMPT should instruct to use user_timezone variable"

    def test_reclassify_prompt_contains_singapore_timezone_example(self):
        """Test that prompt contains explicit example with Singapore timezone for time conversion."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should contain the specific example showing Singapore timezone
        # This is the required instruction per the task specification
        assert "Asia/Singapore" in prompt_text, (
            "RECLASSIFY_PROMPT should contain explicit example with Asia/Singapore timezone"
        )

    def test_reclassify_prompt_contains_time_computation_example(self):
        """Test that prompt contains example showing time computation (e.g., 5pm = 17:00, 17:00 - 8 hours = 09:00 UTC)."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should show the specific computation example
        assert "17:00" in prompt_text or "5pm" in prompt_text.lower(), (
            "RECLASSIFY_PROMPT should contain example showing time computation"
        )
        assert "UTC" in prompt_text, (
            "RECLASSIFY_PROMPT should explicitly mention UTC in the time conversion example"
        )

    def test_reclassify_prompt_warns_not_to_assume_utc(self):
        """Test that prompt warns against assuming times are in UTC."""
        prompt_text = RECLASSIFY_PROMPT

        # The prompt should warn NOT to assume times are in UTC
        assert (
            "NOT assume" in prompt_text or "do not assume" in prompt_text.lower()
        ) and "UTC" in prompt_text, (
            "RECLASSIFY_PROMPT should explicitly warn NOT to assume times are in UTC"
        )
