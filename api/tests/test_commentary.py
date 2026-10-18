"""Chat step lines speak plainly: no raw code (snake_case) reaches the line the owner reads; the code stays in details."""

import re

from nightlight_api import turns

SNAKE = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


def _cases():
    codes = [*turns.REASON_WORDS, "some_new_code", "update_helper_first", "strict_device"]
    for code in codes:
        yield "propose_fix", {"status": "error", "reason": code}
        yield "propose_fix", {"status": "refused", "reason": code}
        yield "propose_fix", {"error": code}
    for status in [*turns.STATUS_WORDS, "brand_new_status", "linked"]:
        yield "anything", {"status": status}
        yield "use_runbook", {"status": status, "runbook": "Clear old app downloads"}
        yield "propose_fix", {"status": "safer_first", "proposed": {"status": "done" if status != "x" else status,
                                                                    "result": "Freed 1 GB."}}
        yield "inspect", {"status": "done" if status == "done" else "failed", "output": ""}


def test_no_step_line_shows_a_raw_code():
    for name, resp in _cases():
        line, _ = turns._commentary(name, resp)
        assert not SNAKE.search(line), (name, resp, line)


def test_known_codes_read_as_sentences_and_keep_the_code_in_details():
    line, details = turns._commentary("propose_fix", {"status": "error", "reason": "strict_device"})
    assert line == "Couldn't: This device only allows changes made on the device itself"
    assert details == "Code: strict_device"
    line, details = turns._commentary("propose_fix", {"status": "error", "reason": "brand_new_code"})
    assert "brand_new_code" not in line and details == "Code: brand_new_code"
    line, details = turns._commentary("x", {"status": "brand_new_status"})
    assert line == "Step finished" and details == "Status: brand_new_status"


def test_reasons_already_in_words_stay_as_they_are():
    line, details = turns._commentary("x", {"status": "error", "reason": "the device isn't reporting right now"})
    assert line == "Couldn't: the device isn't reporting right now" and details is None


def test_words_mixed_with_codes_read_plainly_with_the_list_in_details():
    reason = "a step's job must be one of: backup_world, clear_images, restart_app"
    for resp in ({"status": "refused", "reason": reason}, {"status": "error", "reason": "bad: some_code here"}):
        line, details = turns._commentary("save_runbook", resp)
        assert not SNAKE.search(line) and details == resp["reason"], line
    assert turns._commentary("save_runbook", {"status": "refused", "reason": reason})[0] == \
        "Couldn't: a step's job must be one of (see the details)"


def test_saved_fixes_not_runbooks():
    line, _ = turns._commentary("use_runbook", {"runbook": "Clear old app downloads", "actionIds": ["a", "b"]})
    assert line == "Saved fix \"Clear old app downloads\": 2 step(s) waiting for your OK"
    assert "runbook" not in line.lower()
