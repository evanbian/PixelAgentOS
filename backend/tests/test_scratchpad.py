"""Tests for scratchpad.py — thread safety and read/write semantics."""
from __future__ import annotations
import threading
import pytest
from agents.scratchpad import Scratchpad, ScratchpadEntry


class TestScratchpadWrite:
    def test_write_returns_confirmation(self):
        sp = Scratchpad(task_id="t1")
        result = sp.write("key1", "content1", "a1", "Alice")
        assert "Written to scratchpad" in result
        assert "key1" in result

    def test_write_stores_entry(self):
        sp = Scratchpad(task_id="t1")
        sp.write("findings", "some data", "a1", "Alice")
        assert "findings" in sp.keys()

    def test_write_overwrites_same_key(self):
        sp = Scratchpad(task_id="t1")
        sp.write("findings", "v1", "a1", "Alice")
        sp.write("findings", "v2", "a2", "Bob")
        result = sp.read("findings")
        assert "v2" in result
        assert "Bob" in result

    def test_write_multiple_keys(self):
        sp = Scratchpad(task_id="t1")
        sp.write("research", "data1", "a1", "Alice")
        sp.write("analysis", "data2", "a2", "Bob")
        keys = sp.keys()
        assert "research" in keys
        assert "analysis" in keys


class TestScratchpadRead:
    def test_read_specific_key(self):
        sp = Scratchpad(task_id="t1")
        sp.write("key1", "hello world", "a1", "Alice")
        result = sp.read("key1")
        assert "hello world" in result
        assert "Alice" in result

    def test_read_missing_key(self):
        sp = Scratchpad(task_id="t1")
        result = sp.read("nonexistent")
        assert "No entry found" in result

    def test_read_all_empty(self):
        sp = Scratchpad(task_id="t1")
        result = sp.read()
        assert "empty" in result.lower()

    def test_read_all_multiple_entries(self):
        sp = Scratchpad(task_id="t1")
        sp.write("k1", "content1", "a1", "Alice")
        sp.write("k2", "content2", "a2", "Bob")
        result = sp.read()
        assert "content1" in result
        assert "content2" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_read_all_with_none_key(self):
        sp = Scratchpad(task_id="t1")
        sp.write("k1", "data", "a1", "Alice")
        result = sp.read(None)
        assert "data" in result

    def test_read_empty_string_key_reads_all(self):
        """read('') should behave like read(None) — read all."""
        sp = Scratchpad(task_id="t1")
        sp.write("k1", "data", "a1", "Alice")
        # empty string is falsy in Python, so read("") → read all
        result = sp.read("")
        assert "data" in result


class TestScratchpadKeys:
    def test_keys_empty(self):
        sp = Scratchpad(task_id="t1")
        assert sp.keys() == []

    def test_keys_after_writes(self):
        sp = Scratchpad(task_id="t1")
        sp.write("a", "1", "a1", "Alice")
        sp.write("b", "2", "a1", "Alice")
        keys = sp.keys()
        assert set(keys) == {"a", "b"}


class TestScratchpadThreadSafety:
    def test_concurrent_writes(self):
        """Multiple threads writing simultaneously should not lose entries."""
        sp = Scratchpad(task_id="t1")
        errors = []

        def writer(key_prefix: str, count: int):
            try:
                for i in range(count):
                    sp.write(f"{key_prefix}_{i}", f"val_{i}", "a1", "Writer")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(f"t{t}", 20))
            for t in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 5 threads × 20 writes = 100 unique keys
        assert len(sp.keys()) == 100

    def test_concurrent_read_write(self):
        """Reading while writing should not raise exceptions."""
        sp = Scratchpad(task_id="t1")
        errors = []
        stop_event = threading.Event()

        def writer():
            try:
                for i in range(50):
                    sp.write(f"k_{i}", f"content_{i}", "a1", "Writer")
            except Exception as e:
                errors.append(e)
            finally:
                stop_event.set()

        def reader():
            try:
                while not stop_event.is_set():
                    sp.read()
                    sp.keys()
            except Exception as e:
                errors.append(e)

        w = threading.Thread(target=writer)
        r = threading.Thread(target=reader)
        r.start()
        w.start()
        w.join()
        r.join(timeout=5)

        assert not errors


class TestScratchpadEntry:
    def test_entry_creation(self):
        entry = ScratchpadEntry("key", "content", "a1", "Alice")
        assert entry.key == "key"
        assert entry.content == "content"
        assert entry.author_id == "a1"
        assert entry.author_name == "Alice"
        assert entry.updated_at is not None
