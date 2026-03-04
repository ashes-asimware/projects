from azure.servicebus import ServiceBusClient


class ServiceBusPublisher:
    def __init__(self, connection_string: str | None = None) -> None:
        self.connection_string = connection_string

    def send(self, queue_name: str, message: str) -> bool:
        if not self.connection_string:
            return False
        with ServiceBusClient.from_connection_string(self.connection_string) as client:
            with client.get_queue_sender(queue_name=queue_name) as sender:
                from azure.servicebus import ServiceBusMessage

                sender.send_messages(ServiceBusMessage(message))
        return True
