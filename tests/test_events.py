from mate.core.events import EventBus


def test_event_bus_invokes_subscribers():
    bus = EventBus()
    received = []
    bus.subscribe("topic", lambda payload: received.append(payload))
    bus.emit("topic", 42)
    assert received == [42]
