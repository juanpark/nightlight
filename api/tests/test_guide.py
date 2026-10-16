"""The agent's guide to Nightlight itself: every topic it is told about exists, and unknown topics list the real ones."""

import re

from nightlight_api import agent, guide


def test_every_topic_named_to_the_agent_exists():
    ctx = agent.TurnContext.__new__(agent.TurnContext)
    tool = next(t for t in agent.make_tools(ctx, read_only=True) if t.__name__ == "how_nightlight_works")
    named = re.findall(r"[a-z_]+", tool.__doc__.split("Topics:")[1].split("Args:")[0].replace("topic", ""))
    assert set(named) == set(guide.topics())


def test_topics_read_plainly_and_unknown_ones_list_the_rest():
    got = guide.read("Remove device")
    assert got["title"] == "Remove a device" and "uninstall.sh" in got["text"] and "{web}" not in got["text"]
    assert "remove_device" in guide.read("teleport")["topics"]


def test_no_secret_shapes_in_the_guide():
    from nightlight_api.redact import scrub
    for t in guide.topics().values():
        assert scrub(t["text"])[1] == 0
