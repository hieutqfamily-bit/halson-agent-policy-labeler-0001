"""Work queue between the API (producer) and the labeling workers (consumers).

Two queues, as in the design: `live` for new postings (latency-bound) and `backfill` for
re-labels after a policy change (throughput-bound, never allowed to starve live traffic).
Each has a dead-letter queue: a message that fails 3 receives is parked there, not retried
forever.

Production: Amazon SQS. Local compose: ElasticMQ, which speaks the SQS API, so `SQSQueue`
is the production code path with a different endpoint. Tests and `make dev`: `MemoryQueue`.
At-least-once delivery either way; the worker is idempotent (see DB.mark_item).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

QueueName = Literal["live", "backfill"]


@dataclass(frozen=True)
class Message:
    body: dict[str, Any]
    receipt: str
    receive_count: int = 1


class WorkQueue(Protocol):
    async def send(self, queue: QueueName, bodies: list[dict[str, Any]]) -> None: ...
    async def receive(self, queue: QueueName, max_messages: int, wait_s: float) -> list[Message]: ...
    async def ack(self, queue: QueueName, msg: Message) -> None: ...
    async def depth(self, queue: QueueName) -> dict[str, int]: ...


# ---- SQS / ElasticMQ -----------------------------------------------------------
class SQSQueue:
    def __init__(self, names: dict[QueueName, str], endpoint_url: str | None, region: str):
        import boto3

        self.client = boto3.client("sqs", endpoint_url=endpoint_url, region_name=region)
        self.names = names
        self._urls: dict[QueueName, str] = {}

    def _url(self, queue: QueueName) -> str:
        if queue not in self._urls:
            self._urls[queue] = self.client.get_queue_url(QueueName=self.names[queue])["QueueUrl"]
        return self._urls[queue]

    def ensure(self, visibility_timeout_s: int = 300, max_receives: int = 3) -> None:
        """Create missing queues, each with a DLQ and redrive policy. Existing queues (pre-declared in
        ElasticMQ's config, or by infrastructure-as-code on AWS) are used as they are."""
        from botocore.exceptions import ClientError

        def existing(name: str) -> str | None:
            try:
                return self.client.get_queue_url(QueueName=name)["QueueUrl"]
            except ClientError:
                return None

        for q, name in self.names.items():
            url = existing(name)
            if url is None:
                dlq_url = existing(f"{name}-dlq") or self.client.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
                dlq_arn = self.client.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"][
                    "QueueArn"
                ]
                redrive = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(max_receives)}
                url = self.client.create_queue(
                    QueueName=name,
                    Attributes={"VisibilityTimeout": str(visibility_timeout_s), "RedrivePolicy": json.dumps(redrive)},
                )["QueueUrl"]
            self._urls[q] = url

    async def send(self, queue: QueueName, bodies: list[dict[str, Any]]) -> None:
        url = self._url(queue)
        for i in range(0, len(bodies), 10):  # SQS batch limit
            entries = [{"Id": str(n), "MessageBody": json.dumps(b)} for n, b in enumerate(bodies[i : i + 10])]
            resp = await asyncio.to_thread(self.client.send_message_batch, QueueUrl=url, Entries=entries)
            if resp.get("Failed"):
                raise RuntimeError(f"SQS rejected {len(resp['Failed'])} messages: {resp['Failed'][0]}")

    async def receive(self, queue: QueueName, max_messages: int, wait_s: float) -> list[Message]:
        resp = await asyncio.to_thread(
            self.client.receive_message,
            QueueUrl=self._url(queue),
            MaxNumberOfMessages=max(1, min(10, max_messages)),
            WaitTimeSeconds=int(wait_s),
            AttributeNames=["ApproximateReceiveCount"],
        )
        return [
            Message(
                body=json.loads(m["Body"]),
                receipt=m["ReceiptHandle"],
                receive_count=int(m.get("Attributes", {}).get("ApproximateReceiveCount", 1)),
            )
            for m in resp.get("Messages", [])
        ]

    async def ack(self, queue: QueueName, msg: Message) -> None:
        await asyncio.to_thread(self.client.delete_message, QueueUrl=self._url(queue), ReceiptHandle=msg.receipt)

    async def depth(self, queue: QueueName) -> dict[str, int]:
        attrs = (
            await asyncio.to_thread(
                self.client.get_queue_attributes,
                QueueUrl=self._url(queue),
                AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
            )
        )["Attributes"]
        return {
            "visible": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
        }


# ---- in-process -----------------------------------------------------------------
@dataclass
class _Entry:
    body: dict[str, Any]
    receives: int = 0
    invisible_until: float = 0.0


@dataclass
class MemoryQueue:
    """Same semantics as SQS in miniature: visibility timeout, redelivery, DLQ after N receives."""

    visibility_timeout_s: float = 300.0
    max_receives: int = 3
    _q: dict[str, dict[str, _Entry]] = field(default_factory=lambda: {"live": {}, "backfill": {}})
    dlq: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: {"live": [], "backfill": []})
    _cond: asyncio.Condition | None = None

    def _condition(self) -> asyncio.Condition:
        if self._cond is None:
            self._cond = asyncio.Condition()
        return self._cond

    async def send(self, queue: QueueName, bodies: list[dict[str, Any]]) -> None:
        for b in bodies:
            self._q[queue][uuid.uuid4().hex] = _Entry(body=b)
        async with self._condition():
            self._condition().notify_all()

    def _take(self, queue: QueueName, n: int) -> list[Message]:
        t = time.monotonic()
        out: list[Message] = []
        for receipt, e in list(self._q[queue].items()):
            if len(out) >= n:
                break
            if e.invisible_until > t:
                continue
            if e.receives >= self.max_receives:
                self.dlq[queue].append(e.body)
                del self._q[queue][receipt]
                continue
            e.receives += 1
            e.invisible_until = t + self.visibility_timeout_s
            out.append(Message(body=e.body, receipt=receipt, receive_count=e.receives))
        return out

    async def receive(self, queue: QueueName, max_messages: int, wait_s: float) -> list[Message]:
        msgs = self._take(queue, max_messages)
        if msgs or wait_s <= 0:
            return msgs
        cond = self._condition()
        async with cond:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(cond.wait(), timeout=wait_s)
        return self._take(queue, max_messages)

    async def ack(self, queue: QueueName, msg: Message) -> None:
        self._q[queue].pop(msg.receipt, None)

    async def depth(self, queue: QueueName) -> dict[str, int]:
        t = time.monotonic()
        entries = self._q[queue].values()
        return {
            "visible": sum(1 for e in entries if e.invisible_until <= t),
            "in_flight": sum(1 for e in entries if e.invisible_until > t),
        }
