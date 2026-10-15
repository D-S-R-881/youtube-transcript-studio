import threading

from app.services.segments import SegmentCollector, strip_overlap


def test_exact_duplicates_dropped_when_refetching_live_captions():
    c = SegmentCollector()
    batch = [(0.0, 2.0, "hello there"), (2.0, 4.0, "how are you")]
    for b in batch:
        c.add(*b)
    # A later poll returns the full list again plus a new segment.
    for b in batch + [(4.0, 6.0, "new line")]:
        c.add(*b)
    assert [s.text for s in c.snapshot()] == ["hello there", "how are you", "new line"]
    assert [s.id for s in c.snapshot()] == [1, 2, 3]
    assert c.dropped_duplicates == 2


def test_near_duplicate_within_window_dropped():
    c = SegmentCollector()
    c.add(10.0, 12.0, "Thanks for watching!")
    assert c.add(13.0, 15.0, "thanks for watching") is None
    assert c.add(40.0, 42.0, "Thanks for watching!") is not None


def test_near_duplicate_disabled_for_files():
    c = SegmentCollector(near_duplicate_window=0)
    c.add(0.0, 1.0, "Thank you.")
    assert c.add(1.0, 2.0, "Thank you.") is not None


def test_ordering_preserved_and_out_of_order_dropped():
    c = SegmentCollector()
    c.add(10.0, 12.0, "b")
    assert c.add(2.0, 3.0, "a stale revision") is None
    c.add(12.0, 14.0, "c")
    starts = [s.start for s in c.snapshot()]
    assert starts == sorted(starts)
    assert c.dropped_out_of_order == 1


def test_overlap_between_chunks_is_stripped():
    c = SegmentCollector()
    c.add(0.0, 15.0, "and that is why we need to build better tools")
    seg = c.add(14.5, 18.0, "build better tools for everyone")
    assert seg is not None and seg.text == "for everyone"


def test_fully_overlapping_chunk_dropped():
    c = SegmentCollector()
    c.add(0.0, 5.0, "one two three four")
    assert c.add(4.8, 6.0, "three four") is None


def test_strip_overlap_unit():
    assert strip_overlap("a b c d", "c d e") == "e"
    assert strip_overlap("a b c", "x y z") == "x y z"
    assert strip_overlap("Hello, World!", "world! again") == "world! again"  # single word < min_words
    assert strip_overlap("We said hello world", "Hello, world. Again") == "Again"


def test_empty_text_ignored():
    c = SegmentCollector()
    assert c.add(0, 1, "   ") is None
    assert c.add(0, 1, "...") is None
    assert len(c) == 0


def test_thread_safety():
    c = SegmentCollector(near_duplicate_window=0)

    def worker(base):
        for i in range(200):
            c.add(float(base * 1000 + i), float(base * 1000 + i + 1), f"w{base}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = [s.id for s in c.snapshot()]
    assert ids == list(range(1, len(ids) + 1))
