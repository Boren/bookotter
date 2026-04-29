import logging

from backend.utils.events import log_event


class TestLogEvent:
    def test_log_event_emits_parseable_line(self, caplog):
        with caplog.at_level(logging.INFO, logger="backend.utils.events"):
            log_event("test_event", book_id=42, duration_ms=100)

        assert any("event=test_event" in r.message for r in caplog.records)
        assert any("book_id=42" in r.message for r in caplog.records)
        assert any("duration_ms=100" in r.message for r in caplog.records)

    def test_log_event_handles_various_types(self, caplog):
        with caplog.at_level(logging.INFO, logger="backend.utils.events"):
            log_event("pipeline_run_started", run_id="abc123", holder="scheduled")

        assert any("event=pipeline_run_started" in r.message for r in caplog.records)
        assert any("run_id=abc123" in r.message for r in caplog.records)
        assert any("holder=scheduled" in r.message for r in caplog.records)

    def test_log_event_emits_at_info_level(self, caplog):
        with caplog.at_level(logging.INFO, logger="backend.utils.events"):
            log_event("level_check")

        records = [r for r in caplog.records if r.name == "backend.utils.events"]
        assert len(records) == 1
        assert records[0].levelno == logging.INFO

    def test_log_event_with_no_fields(self, caplog):
        with caplog.at_level(logging.INFO, logger="backend.utils.events"):
            log_event("bare_event")

        assert any(r.message == "event=bare_event" for r in caplog.records)
