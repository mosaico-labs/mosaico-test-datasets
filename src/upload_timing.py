"""
Upload timing instrumentation for the Mosaico ROS injector.

Splits the wall-clock time of a ``RosbagInjector.run()`` call into the time
spent blocked on the Mosaico server and the time spent in client-side Python
code. The Python time is further split into rosbag reading and Mosaico SDK
processing.

The SDK upload pipeline is fully synchronous and single-threaded, so the
server time can be measured by timing every blocking call that reaches the
server, and the Python time is what remains:

- ``FlightStreamWriter.write``: sends one batch over the ``DoPut`` stream. It
  blocks on gRPC flow control, so it measures network transfer plus the
  server's ingestion throughput.
- ``FlightStreamWriter.done_writing`` / ``close``: wait for the server to
  drain and acknowledge the topic stream.
- ``_do_action``: request/response RPCs (session create, topic create,
  finalize, sequence listing, ...).

Rosbag reading is every call that touches the bag file: everything done by
the ``rosbags`` library through ``AnyReader`` (path checks in the constructor,
opening and indexing the bag in ``open``, reading the raw messages in
``messages``, deserializing them in ``deserialize``, ``close``) plus the SDK's
own file checks (``ROSLoader._validate_file``). All file I/O, and therefore
the cost of slow storage such as a NAS, ends up here. The SDK time is the
remaining Python time: ROS message to dict conversion, adapter translation,
Arrow conversion, injector logic and UI.

NOTE: this patches private SDK internals (``_TopicWriteState`` and the
``_do_action`` references imported by each SDK module), so it may need
updating when the SDK changes.
"""

import importlib
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from mosaicolabs.bridges.ros.loader import ROSLoader
from mosaicolabs.handlers.internal.topic_write_state import _TopicWriteState
from rosbags.highlevel import AnyReader

# SDK modules that import ``_do_action`` by name: each one keeps its own
# reference, so each one must be patched.
_DO_ACTION_MODULES = [
    "mosaicolabs.comm.connection",
    "mosaicolabs.comm.mosaico_client",
    "mosaicolabs.handlers.base_session_writer",
    "mosaicolabs.handlers.sequence_writer",
    "mosaicolabs.handlers.topic_writer",
]


@dataclass
class UploadTiming:
    """Timing breakdown (in seconds) of a single upload."""

    total_s: float = 0.0
    write_s: float = 0.0  # DoPut batch transfers
    finalize_s: float = 0.0  # DoPut done_writing/close (server drain + ack)
    rpc_s: float = 0.0  # do_action round-trips
    rosbag_s: float = 0.0  # all bag file access + deserialize (subset of python_s)
    serialize_s: float = 0.0  # Python -> Arrow RecordBatch (subset of sdk_s)
    n_batches: int = 0
    n_rpcs: int = 0
    rpc_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def server_s(self) -> float:
        return self.write_s + self.finalize_s + self.rpc_s

    @property
    def python_s(self) -> float:
        return self.total_s - self.server_s

    @property
    def sdk_s(self) -> float:
        return self.python_s - self.rosbag_s


class _TimedFlightWriter:
    """Proxy around a ``FlightStreamWriter`` that times the blocking calls."""

    def __init__(self, writer, timing: UploadTiming):
        self._writer = writer
        self._timing = timing

    def write(self, batch):
        start = time.perf_counter()
        try:
            return self._writer.write(batch)
        finally:
            self._timing.write_s += time.perf_counter() - start
            self._timing.n_batches += 1

    def done_writing(self):
        start = time.perf_counter()
        try:
            return self._writer.done_writing()
        finally:
            self._timing.finalize_s += time.perf_counter() - start

    def close(self):
        start = time.perf_counter()
        try:
            return self._writer.close()
        finally:
            self._timing.finalize_s += time.perf_counter() - start

    def __getattr__(self, name):
        return getattr(self._writer, name)


@contextmanager
def measure_upload():
    """Instrument the SDK for the duration of the block.

    Yields:
        UploadTiming: filled in when the block exits (also on error).
    """

    timing = UploadTiming()

    orig_init = _TopicWriteState.__init__
    orig_get_record_batch = _TopicWriteState._get_record_batch

    def timed_init(self, topic_name, data_schema, writer, max_batch_size_bytes):
        if writer is not None:
            writer = _TimedFlightWriter(writer, timing)
        orig_init(self, topic_name, data_schema, writer, max_batch_size_bytes)

    def timed_get_record_batch(self, msgs):
        start = time.perf_counter()
        try:
            return orig_get_record_batch(self, msgs)
        finally:
            timing.serialize_s += time.perf_counter() - start

    def timed_rosbag(func):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                timing.rosbag_s += time.perf_counter() - start

        return wrapper

    # (owner, attribute) pairs whose whole call is rosbag reading
    rosbag_calls = [
        (AnyReader, "__init__"),
        (AnyReader, "open"),
        (AnyReader, "deserialize"),
        (AnyReader, "close"),
        (ROSLoader, "_validate_file"),
    ]
    orig_rosbag_calls = [
        (owner, name, getattr(owner, name)) for owner, name in rosbag_calls
    ]
    orig_reader_messages = AnyReader.messages

    def timed_reader_messages(self, *args, **kwargs):
        # Times each step of the underlying generator, not the consumer's work
        messages = orig_reader_messages(self, *args, **kwargs)
        try:
            while True:
                start = time.perf_counter()
                try:
                    item = next(messages)
                except StopIteration:
                    return
                finally:
                    timing.rosbag_s += time.perf_counter() - start
                yield item
        finally:
            messages.close()

    patched_modules = []
    for mod_name in _DO_ACTION_MODULES:
        module = importlib.import_module(mod_name)
        orig_do_action = getattr(module, "_do_action", None)
        if orig_do_action is None:
            continue

        def timed_do_action(*args, _orig=orig_do_action, **kwargs):
            action = kwargs.get("action", args[1] if len(args) > 1 else "?")
            start = time.perf_counter()
            try:
                return _orig(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                timing.rpc_s += elapsed
                timing.n_rpcs += 1
                key = getattr(action, "value", str(action))
                timing.rpc_breakdown[key] = timing.rpc_breakdown.get(key, 0.0) + elapsed

        setattr(module, "_do_action", timed_do_action)
        patched_modules.append((module, orig_do_action))

    _TopicWriteState.__init__ = timed_init
    _TopicWriteState._get_record_batch = timed_get_record_batch
    for owner, name, orig in orig_rosbag_calls:
        setattr(owner, name, timed_rosbag(orig))
    AnyReader.messages = timed_reader_messages

    start = time.perf_counter()
    try:
        yield timing
    finally:
        timing.total_s = time.perf_counter() - start
        _TopicWriteState.__init__ = orig_init
        _TopicWriteState._get_record_batch = orig_get_record_batch
        for owner, name, orig in orig_rosbag_calls:
            setattr(owner, name, orig)
        AnyReader.messages = orig_reader_messages
        for module, orig_do_action in patched_modules:
            setattr(module, "_do_action", orig_do_action)
