# System Event Bus definition

import time
import uuid
from typing import List, Dict, Any, Callable
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Event:
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    source: str = ""
    timestamp: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)

class EventBus:
    def __init__(self):
        self._listeners: Dict[str, List[Callable[[Event], None]]] = {}
        self._history: List[Event] = []

    def subscribe(self, topic: str, callback: Callable[[Event], None]):
        if topic not in self._listeners:
            self._listeners[topic] = []
        self._listeners[topic].append(callback)

    def publish(self, topic: str, source: str, payload: Dict[str, Any]):
        event = Event(topic=topic, source=source, payload=payload)
        self._history.append(event)

        # Notify subscribers
        # Specific topic
        if topic in self._listeners:
            for callback in self._listeners[topic]:
                try:
                    callback(event)
                except Exception as e:
                    # Robust handling so failure in subscriber doesn't crash event publishing
                    print(f"Error in subscriber for {topic}: {e}")
        # Wildcard topic (if registered)
        if "*" in self._listeners:
            for callback in self._listeners["*"]:
                try:
                    callback(event)
                except Exception as e:
                    print(f"Error in wildcard subscriber: {e}")

    def get_history(self) -> List[Event]:
        return list(self._history)
