"""Async LLM client using the OpenAI API."""

import logging

import openai

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM API call fails."""


class LLMClient:
    """Async client for OpenAI-compatible LLM APIs."""

    def __init__(self, base_url: str, api_key: str = "not-needed"):
        self._client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0,
        )

    async def complete(self, model: str, prompt: str) -> str:
        """Text completion via /v1/chat/completions.

        Args:
            model: Model name (e.g. "mistral").
            prompt: User prompt text.

        Returns:
            Assistant response text.

        Raises:
            LLMError: On API or connection failure.
        """
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except (openai.APIError, openai.APIConnectionError) as e:
            raise LLMError(f"LLM API error: {e}") from e

    async def complete_with_image(
        self, model: str, prompt: str, image_b64: str
    ) -> str:
        """Vision completion with base64 image.

        Uses the multi-part content format for vision models.

        Args:
            model: Vision model name (e.g. "llava").
            prompt: Text prompt.
            image_b64: Base64-encoded image string.

        Returns:
            Assistant response text.

        Raises:
            LLMError: On API or connection failure.
        """
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
                temperature=0.3,
                timeout=120.0,
            )
            return response.choices[0].message.content or ""
        except (openai.APIError, openai.APIConnectionError) as e:
            raise LLMError(f"LLM vision API error: {e}") from e

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()