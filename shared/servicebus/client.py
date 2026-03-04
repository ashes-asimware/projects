import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

try:
    from azure.servicebus import ServiceBusClient, ServiceBusMessage
    from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient
except ModuleNotFoundError:  # pragma: no cover - exercised only when optional dependency missing
    ServiceBusClient = None
    ServiceBusMessage = None

    class AsyncServiceBusClient:  # type: ignore[no-redef]
        @staticmethod
        def from_connection_string(*_args: Any, **_kwargs: Any) -> Any:
            raise ModuleNotFoundError("azure-servicebus is required for async Service Bus operations")

DEFAULT_CONNECTION_STRING_ENV_VARS = (
    "AZURE_SERVICEBUS_CONNECTION_STRING",
    "SERVICEBUS_CONNECTION_STRING",
)

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1.0

logger = logging.getLogger(__name__)


class ServiceBusPublisher:
    def __init__(
        self,
        connection_string: str | None = None,
        connection_string_env_vars: tuple[str, ...] = DEFAULT_CONNECTION_STRING_ENV_VARS,
    ) -> None:
        self.connection_string = connection_string or _get_connection_string(connection_string_env_vars)

    def send(self, queue_name: str, message: str) -> bool:
        if not self.connection_string:
            logger.warning("Service Bus connection string is not configured; message not sent")
            return False
        if ServiceBusClient is None or ServiceBusMessage is None:
            logger.warning("azure-servicebus is not installed; message not sent")
            return False
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            with client.get_queue_sender(queue_name=queue_name) as sender:
                sender.send_messages(ServiceBusMessage(message))
        return True


def _get_connection_string(connection_string_env_vars: tuple[str, ...]) -> str | None:
    for env_var in connection_string_env_vars:
        if value := os.getenv(env_var):
            return value
    return None


def _build_message_body(payload: Any) -> str | bytes:
    if isinstance(payload, (str, bytes)):
        return payload
    return json.dumps(payload)


def _decode_message_body(message: Any) -> str:
    body = b"".join(message.body)
    return body.decode("utf-8")


async def _invoke_handler(
    handler: Callable[[str, str | None], Awaitable[None] | None],
    payload: str,
    correlation_id: str | None,
) -> None:
    result = handler(payload, correlation_id)
    if asyncio.iscoroutine(result):
        await result


async def publish(
    topic_name: str,
    payload: Any,
    *,
    correlation_id: str | None = None,
    connection_string: str | None = None,
    connection_string_env_vars: tuple[str, ...] = DEFAULT_CONNECTION_STRING_ENV_VARS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> None:
    resolved_connection_string = connection_string or _get_connection_string(connection_string_env_vars)
    if not resolved_connection_string:
        raise ValueError("Service Bus connection string is not configured")
    if ServiceBusMessage is None:
        raise ModuleNotFoundError("azure-servicebus is required for publish")

    message_correlation_id = correlation_id
    if message_correlation_id is None and isinstance(payload, dict):
        message_correlation_id = payload.get("correlation_id")

    message = ServiceBusMessage(
        _build_message_body(payload),
        correlation_id=message_correlation_id,
    )

    for attempt in range(max_retries + 1):
        try:
            async with AsyncServiceBusClient.from_connection_string(resolved_connection_string) as client:
                sender = client.get_topic_sender(topic_name=topic_name)
                async with sender:
                    await sender.send_messages(message)
            return
        except Exception:
            if attempt >= max_retries:
                raise
            await asyncio.sleep(retry_delay_seconds * (2**attempt))


async def subscribe(
    topic_name: str,
    subscription_name: str,
    handler: Callable[[str, str | None], Awaitable[None] | None],
    *,
    connection_string: str | None = None,
    connection_string_env_vars: tuple[str, ...] = DEFAULT_CONNECTION_STRING_ENV_VARS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    max_message_count: int = 1,
    max_wait_time: int = 5,
) -> int:
    resolved_connection_string = connection_string or _get_connection_string(connection_string_env_vars)
    if not resolved_connection_string:
        raise ValueError("Service Bus connection string is not configured")

    async with AsyncServiceBusClient.from_connection_string(resolved_connection_string) as client:
        receiver = client.get_subscription_receiver(
            topic_name=topic_name,
            subscription_name=subscription_name,
            max_wait_time=max_wait_time,
        )
        async with receiver:
            messages = await receiver.receive_messages(
                max_message_count=max_message_count,
                max_wait_time=max_wait_time,
            )
            for message in messages:
                payload = _decode_message_body(message)
                correlation_id = getattr(message, "correlation_id", None)
                for attempt in range(max_retries + 1):
                    try:
                        await _invoke_handler(handler, payload, correlation_id)
                        await receiver.complete_message(message)
                        break
                    except Exception as exc:
                        if attempt >= max_retries:
                            await receiver.dead_letter_message(
                                message,
                                reason="processing_failed",
                                error_description=str(exc),
                            )
                            break
                        await asyncio.sleep(retry_delay_seconds * (2**attempt))
            return len(messages)
