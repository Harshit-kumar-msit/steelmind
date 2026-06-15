"""
Module: ai/llm/client.py
Purpose: Thin async wrapper around the Groq API.
         Handles retries, timeout, streaming, and token usage logging.
         Uses llama-3.3-70b-versatile as the main model.
         Uses llama-3.1-8b-instant for fast classification tasks.
Inputs:  messages list, optional system prompt, model override
Outputs: str (full response) or async generator (streaming)
Production: Add circuit breaker pattern. Log token usage to PostgreSQL
            for cost tracking. Consider response caching for identical
            queries (vibration questions asked repeatedly per shift).
"""
import asyncio
from typing import AsyncGenerator, Optional
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from loguru import logger
from app.core.config import settings


class GroqClient:
    """Singleton Groq client. Instantiate once in lifespan, inject via dependency."""

    def __init__(self):
        self._client = AsyncGroq(
            api_key=settings.groq_api_key,
            timeout=settings.groq_timeout,
        )
        self.main_model = settings.groq_model          # llama-3.3-70b-versatile
        self.fast_model = settings.groq_fast_model     # llama-3.1-8b-instant

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> str:
        """
        Single-shot completion. Returns the full response string.

        Args:
            messages:      [{role, content}] conversation history
            system_prompt: If provided, prepended as a system message
            model:         Override model (default: main_model)
            temperature:   Override temperature (default: settings.groq_temperature)
            max_tokens:    Override max tokens
            json_mode:     If True, forces JSON response format

        Returns:
            str: LLM response text

        Example:
            response = await groq_client.complete(
                messages=[{"role": "user", "content": "What is bearing spalling?"}],
                system_prompt="You are a maintenance expert."
            )
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        kwargs = {
            "model": model or self.main_model,
            "messages": full_messages,
            "temperature": temperature if temperature is not None else settings.groq_temperature,
            "max_tokens": max_tokens or settings.groq_max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await self._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            logger.debug(
                f"Groq completion | model={kwargs['model']} "
                f"| tokens_in={response.usage.prompt_tokens} "
                f"| tokens_out={response.usage.completion_tokens}"
            )
            return content
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming completion. Yields text chunks as they arrive.
        Use this for the chat copilot to show real-time responses.

        Usage in FastAPI:
            async def endpoint():
                async def generator():
                    async for chunk in groq_client.stream(messages, system):
                        yield f"data: {chunk}\\n\\n"
                return StreamingResponse(generator(), media_type="text/event-stream")
        """
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        stream = await self._client.chat.completions.create(
            model=model or self.main_model,
            messages=full_messages,
            temperature=temperature if temperature is not None else settings.groq_temperature,
            max_tokens=settings.groq_max_tokens,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def classify(self, text: str, categories: list[str]) -> str:
        """
        Fast classification using the small model.
        Returns one of the categories.

        Args:
            text:       Text to classify
            categories: List of valid output labels

        Returns:
            str: One of the provided categories
        """
        prompt = (
            f"Classify the following text into exactly one of these categories: "
            f"{', '.join(categories)}. "
            f"Respond with ONLY the category name, nothing else.\n\n"
            f"Text: {text}"
        )
        result = await self.complete(
            messages=[{"role": "user", "content": prompt}],
            model=self.fast_model,
            temperature=0.0,
            max_tokens=20,
        )
        # Validate and return
        result = result.strip().lower()
        for cat in categories:
            if cat.lower() in result:
                return cat
        return categories[0]   # fallback to first category

    async def extract_json(self, prompt: str, schema_hint: str = "") -> dict:
        """
        Extract structured JSON from a prompt.
        Used for work order extraction, report structuring, etc.
        """
        system = (
            "You are a JSON extraction assistant. "
            "Respond with ONLY valid JSON, no markdown, no explanation. "
            f"Expected schema: {schema_hint}" if schema_hint else
            "Respond with ONLY valid JSON, no markdown, no explanation."
        )
        raw = await self.complete(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=system,
            model=self.fast_model,
            temperature=0.0,
            json_mode=True,
        )
        import json
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"JSON extraction failed, raw: {raw[:200]}")
            return {}


# Singleton instance
groq_client = GroqClient()
