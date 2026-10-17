"""Web research: scrubbed question, sources returned, budgeted, capped per day."""

from types import SimpleNamespace as NS

from nightlight_api import research


class FakeModels:
    def __init__(self):
        self.asked = []

    def generate_content(self, model, contents, config):
        self.asked.append(contents)
        chunk = NS(web=NS(title="apple.com", uri="https://example.com/x"))
        return NS(text="- likely cause: a hung driver", usage_metadata=NS(prompt_token_count=50, total_token_count=400),
                  candidates=[NS(grounding_metadata=NS(grounding_chunks=[chunk]))])


def test_research_scrubs_cites_and_caps(client, started, monkeypatch):
    fake = NS(models=FakeModels())
    out = research.search(started, "1.2.3.4", "panic on host 192.168.1.20 token=" + "abcdef0123456789abcdef", client=fake)
    assert out["status"] == "done" and out["sources"] == [{"title": "apple.com", "url": "https://example.com/x"}]
    assert "192.168.1.20" not in fake.models.asked[0] and "abcdef0123456789abcdef" not in fake.models.asked[0]
    monkeypatch.setattr(research, "PER_DAY", 1)
    assert "daily limit" in research.search(started, "1.2.3.4", "again", client=fake)["reason"]


def test_rev2_names_and_local_hosts_never_leave(client, started):  # rev2 #7
    q = research.anonymise("Juan says my-nas.internal and plex.local crash on Mac mini", ["Mac mini", "Juan"])
    assert "Juan" not in q and "my-nas" not in q and "plex.local" not in q and "Mac mini" not in q


def test_rev3_name_parts_are_hidden(client, started):  # rev3 #2
    from nightlight_api import db
    sample = next(s.id for s in db.devices(started).get())
    db.device(started, sample).update({"name": "Juan's NAS"})
    from conftest import generation
    names = research.home_names(started, generation(started))
    assert "Juan" in names  # the name part, not only the whole device name
    assert "Juan" not in research.anonymise("Juan says the disk is full", names)


def test_rev3_research_tokens_are_reported(client, started):  # rev3 #3
    from types import SimpleNamespace as NS
    out = research.search(started, "1.2.3.4", "kernel panic", client=NS(models=FakeModels()))
    assert out["tokensIn"] == 50 and out["tokensOut"] == 350
