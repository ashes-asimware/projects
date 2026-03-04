import os
import unittest
from unittest.mock import patch

from shared.servicebus import client


class _FakeServiceBusMessage:
    def __init__(self, body, correlation_id=None):
        self.body = body
        self.correlation_id = correlation_id


class _FakeReceivedMessage:
    def __init__(self, body, correlation_id=None):
        self.body = body
        self.correlation_id = correlation_id


class _FakeSender:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.sent_messages = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send_messages(self, message):
        if self.should_fail:
            raise RuntimeError("temporary send failure")
        self.sent_messages.append(message)


class _FakeReceiver:
    def __init__(self, messages):
        self._messages = messages
        self.completed = []
        self.dead_lettered = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def receive_messages(self, max_message_count, max_wait_time):
        return self._messages[:max_message_count]

    async def complete_message(self, message):
        self.completed.append(message)

    async def dead_letter_message(self, message, reason, error_description):
        self.dead_lettered.append((message, reason, error_description))


class _FakeClient:
    def __init__(self, sender=None, receiver=None):
        self._sender = sender
        self._receiver = receiver

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get_topic_sender(self, topic_name):
        return self._sender

    def get_subscription_receiver(self, topic_name, subscription_name, max_wait_time):
        return self._receiver


class ServiceBusClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_uses_env_connection_string_and_propagates_correlation_id(self):
        sender = _FakeSender()
        fake_client = _FakeClient(sender=sender)
        with (
            patch.dict(os.environ, {"AZURE_SERVICEBUS_CONNECTION_STRING": "Endpoint=sb://example/"}, clear=False),
            patch.object(client.AsyncServiceBusClient, "from_connection_string", return_value=fake_client) as from_conn,
            patch.object(client, "ServiceBusMessage", _FakeServiceBusMessage),
        ):
            await client.publish("topic-a", {"correlation_id": "corr-123", "name": "event"})

        from_conn.assert_called_once_with("Endpoint=sb://example/")
        self.assertEqual(sender.sent_messages[0].correlation_id, "corr-123")

    async def test_subscribe_retries_then_completes_and_passes_correlation_id(self):
        message = _FakeReceivedMessage([b'{"id": 1}'], correlation_id="corr-xyz")
        receiver = _FakeReceiver([message])
        fake_client = _FakeClient(receiver=receiver)
        handler_state = {"count": 0, "correlation_id": None}

        async def flaky_handler(payload, correlation_id):
            handler_state["count"] += 1
            handler_state["correlation_id"] = correlation_id
            if handler_state["count"] == 1:
                raise RuntimeError("transient handler failure")

        with patch.object(client.AsyncServiceBusClient, "from_connection_string", return_value=fake_client):
            processed = await client.subscribe(
                "topic-a",
                "sub-a",
                flaky_handler,
                connection_string="Endpoint=sb://example/",
                max_retries=2,
                retry_delay_seconds=0,
            )

        self.assertEqual(processed, 1)
        self.assertEqual(handler_state["count"], 2)
        self.assertEqual(handler_state["correlation_id"], "corr-xyz")
        self.assertEqual(len(receiver.completed), 1)
        self.assertEqual(len(receiver.dead_lettered), 0)

    async def test_subscribe_dead_letters_after_retry_exhaustion(self):
        message = _FakeReceivedMessage([b'{"id": 2}'], correlation_id="corr-dead")
        receiver = _FakeReceiver([message])
        fake_client = _FakeClient(receiver=receiver)

        async def failing_handler(payload, correlation_id):
            raise RuntimeError("permanent handler failure")

        with patch.object(client.AsyncServiceBusClient, "from_connection_string", return_value=fake_client):
            await client.subscribe(
                "topic-a",
                "sub-a",
                failing_handler,
                connection_string="Endpoint=sb://example/",
                max_retries=1,
                retry_delay_seconds=0,
            )

        self.assertEqual(len(receiver.completed), 0)
        self.assertEqual(len(receiver.dead_lettered), 1)
        self.assertEqual(receiver.dead_lettered[0][1], "processing_failed")


if __name__ == "__main__":
    unittest.main()
