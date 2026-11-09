import asyncio
import time

from app.pipeline import Events
from app.store import Store


def test_expired_batches_are_deleted_with_files(tmp_path):
    store = Store(tmp_path)
    batch = store.create_batch("auto")
    doc = store.add_document(batch.id, "a.pdf", "application/pdf", b"%PDF-1.4", "x")
    assert store.original_path(doc).exists()
    assert store.expired_batches(time.time() - 60) == []
    assert store.expired_batches(time.time() + 1) == [batch.id]
    store.delete_batch(batch.id)
    assert store.get_document(doc.id) is None
    assert not store.batch_dir(batch.id).exists()


async def test_events_wake_subscribers_once_per_burst():
    events = Events()
    q = events.subscribe("bat_1")
    events.publish("bat_1")
    events.publish("bat_1")
    assert q.qsize() == 1
    await asyncio.wait_for(q.get(), 1)
    events.unsubscribe("bat_1", q)
    events.publish("bat_1")  # no subscribers is fine
