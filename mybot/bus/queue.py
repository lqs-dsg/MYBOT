import asyncio
from .events import InboundMessage,OutboundMessage
class MessageBus:
    def __init__(self)->None:
        self._inbound_queue:asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self._inbound_queue.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self._inbound_queue.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        await self._outbound_queue.put(msg)


    async def consume_outbound(self) -> OutboundMessage:
        return await self._outbound_queue.get()

    @property
    def inbound_size(self) -> int:
        return self._inbound_queue.qsize()

    @property
    def outbound_size(self) -> int:
        return self._outbound_queue.qsize()
