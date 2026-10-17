"""The helper learns who made the things nearby (the router's UPnP description, mDNS TXT records from the system's
own mDNS service) and all of its own addresses, without any name or address leaving the device, and without ever
waiting for incoming connections (an unattended helper must never raise a firewall prompt). All network answers here
are canned."""

import importlib.util
import json
import sys
import time

import pytest

from test_helper_client import KEY, SPEC, helper  # noqa: F401 (the fixture)

DESCRIPTION = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <device>
    <deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType>
    <friendlyName>Juan's Router</friendlyName>
    <manufacturer>NETGEAR, Inc.</manufacturer>
    <modelName>Nighthawk</modelName>
    <modelNumber>R7000</modelNumber>
    <serialNumber>4AB12345</serialNumber>
    <deviceList><device><manufacturer>Other</manufacturer></device></deviceList>
  </device>
</root>"""
BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<root><device><manufacturer>&lol2;</manufacturer></device></root>"""
ZONE = """; To direct clients to browse a different domain, substitute that domain in place of '@'
lb._dns-sd._udp                                 PTR     @

_ipp._tcp                                       PTR     Juan's\\032Printer._ipp._tcp
Juan's\\032Printer._ipp._tcp                     SRV     0 0 631 BRN3C2AF4.local. ; Replace with unicast FQDN of target host
Juan's\\032Printer._ipp._tcp                     TXT     "txtvers=1" "ty=Brother HL-L2350DW series" "note=Juan\\'s room"
"""
AVAHI = ('+;en0;IPv4;Juan\\039s Printer;_ipp._tcp;local\n'
         '=;eth0;IPv4;Juan\\039s Printer;_ipp._tcp;local;BRN3C2AF4.local;192.168.1.40;631;'
         '"usb_MDL=HL-L2350DW series" "usb_MFG=Brother" "ty=Brother HL-L2350DW series"\n'
         '=;eth0;IPv4;Living Room;_airplay._tcp;local;Living-Room.local;192.168.1.41;7000;"model=AppleTV14\\0441"\n'
         '=;eth0;IPv6;Living Room;_airplay._tcp;local;Living-Room.local;fe80::1;7000;"model=AppleTV14,1"\n'
         '=;eth0;IPv4;Somewhere;_ipp._tcp;local;x.local;8.8.8.8;631;"ty=HP LaserJet"\n')


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    """The helper as shipped (no stand-ins), for testing the parts that ask; each test replaces what would talk."""
    monkeypatch.setenv("NIGHTLIGHT_HOME", str(tmp_path / "cfg"))
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_description", lambda url, timeout: pytest.fail("no real request"))
    monkeypatch.setattr(mod, "_watch", lambda cmds, seconds: pytest.fail("no real listing"))
    return mod


def test_nothing_in_the_helper_waits_for_incoming_traffic():
    source = open(SPEC.origin).read()
    for word in (".bind(", ".listen(", ".recvfrom(", "recv(", "IP_ADD_MEMBERSHIP", "M-SEARCH", "239.255.255.250"):
        assert word not in source, word


def test_the_router_description_is_asked_of_the_router_only(fresh, monkeypatch):
    monkeypatch.setattr(fresh, "_gateway", lambda: "192.168.1.1")
    asked = []

    def answer(url, timeout):
        asked.append((url, timeout))
        return DESCRIPTION if ":49152/" in url else b""
    monkeypatch.setattr(fresh, "_description", answer)
    router, about = fresh._router_about(5)
    assert router == "192.168.1.1" and about == {"maker": "NETGEAR, Inc.", "model": "Nighthawk R7000",
                                                  "kind": "router"}
    assert all(u.startswith("http://192.168.1.1:") and t <= 1.0 for u, t in asked) and len(asked) == 3
    monkeypatch.setattr(fresh, "_gateway", lambda: "8.8.8.8")
    assert fresh._router_about(5) == (None, {})  # not a private address: not asked

    def slow(url, timeout):
        time.sleep(timeout)
        return b""
    monkeypatch.setattr(fresh, "_gateway", lambda: "192.168.1.1")
    monkeypatch.setattr(fresh, "_description", slow)
    t = time.monotonic()
    assert fresh._router_about(1.5) == ("192.168.1.1", {})
    assert time.monotonic() - t < 2.0  # one deadline for every place


def test_a_description_gives_maker_model_and_kind_never_the_friendly_name(helper):
    assert helper._upnp_about(DESCRIPTION) == {"maker": "NETGEAR, Inc.", "model": "Nighthawk R7000", "kind": "router"}
    assert helper._upnp_about(BOMB) == {}  # refused unread
    assert helper._upnp_about(DESCRIPTION + b" " * helper.DESCRIPTION_BYTES) == {}  # too big to be a description
    assert helper._upnp_about(b"<root><device>") == {} and helper._upnp_about(b"") == {}


def test_a_description_is_read_with_a_size_cap(helper):
    import http.server
    from test_helper_client import _server

    class Big(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * (helper.DESCRIPTION_BYTES * 2))

        def log_message(self, *a):
            pass
    srv = _server(Big)
    try:
        assert len(helper._description(f"http://127.0.0.1:{srv.server_port}/d.xml", 2)) == helper.DESCRIPTION_BYTES + 1
    finally:
        srv.shutdown()
    assert helper._description("http://127.0.0.1:1/x", 1) == b""  # nothing there: no error


def test_mdns_records_come_from_avahi_on_linux(fresh, monkeypatch):
    monkeypatch.setattr(fresh.shutil, "which", lambda n: "/usr/bin/avahi-browse" if n == "avahi-browse" else None)
    monkeypatch.setattr(fresh, "_run", lambda cmd, timeout=20: AVAHI if cmd[0] == "avahi-browse" else "")
    got = fresh._mdns_records()
    assert got == [("192.168.1.40", "_ipp._tcp", {"usb_MDL": "HL-L2350DW series", "usb_MFG": "Brother",
                                                  "ty": "Brother HL-L2350DW series"}),
                   ("192.168.1.41", "_airplay._tcp", {"model": "AppleTV14,1"})]  # no link-local, no public
    assert fresh._mdns() == {"192.168.1.40": {"printer"}, "192.168.1.41": {"AirPlay speaker or TV"}}


def test_mdns_records_come_from_dns_sd_on_a_mac_within_the_time(fresh, monkeypatch):
    monkeypatch.setattr(fresh.shutil, "which", lambda n: "/usr/bin/dns-sd" if n == "dns-sd" else None)
    monkeypatch.setattr(fresh.sys, "platform", "darwin")
    ran = []
    monkeypatch.setattr(fresh, "_watch", lambda cmds, seconds: ran.append((cmds, seconds)) or
                        [ZONE if c[2] == "_ipp._tcp" else "" for c in cmds])
    monkeypatch.setattr(fresh, "_resolve", lambda host, timeout=3: "192.168.1.40" if host == "BRN3C2AF4.local" else None)
    got = fresh._mdns_records(seconds=2)
    assert got == [("192.168.1.40", "_ipp._tcp", {"txtvers": "1", "ty": "Brother HL-L2350DW series",
                                                  "note": "Juan's room"})]
    assert ran[0][1] == 2 and all(c[:2] == ["dns-sd", "-Z"] for c in ran[0][0])  # asked of the system, side by side


def test_listings_that_never_end_are_stopped_in_time(helper):
    t = time.monotonic()
    out = helper._watch([[sys.executable, "-c", "print('first', flush=True); import time; time.sleep(30)"]], 1.0)
    assert out == ["first\n"] and time.monotonic() - t < 3
    assert helper._watch([["/nonexistent/dns-sd"]], 0.5) == []


def test_txt_records_give_printer_and_apple_models(helper):
    assert helper._txt_about("_ipp._tcp", {"ty": "Brother HL-L2350DW series"}) == {"maker": "Brother",
                                                                                   "model": "HL-L2350DW series"}
    assert helper._txt_about("_ipp._tcp", {"ty": "x", "usb_MFG": "EPSON", "usb_MDL": "ET-2850 Series"}) \
        == {"maker": "EPSON", "model": "ET-2850 Series"}
    assert helper._txt_about("_device-info._tcp", {"model": "Macmini9,1"}) == {"maker": "Apple", "model": "Mac mini"}
    assert helper._txt_about("_airplay._tcp", {"model": "AppleTV14,1"}) == {"maker": "Apple", "model": "Apple TV"}
    assert helper._txt_about("_airplay._tcp", {"model": "MacBookPro18,3"})["model"] == "MacBook Pro"
    assert helper._txt_about("_device-info._tcp", {"model": "J314sAP"}) == {}  # an unknown code: nothing
    assert helper._txt_about("_airplay._tcp", {"model": "Zork9,1"}) == {}
    assert helper._txt('"a=b\\032c" "noequals" "a=second" "k=v=w"') == {"a": "b c", "k": "v=w"}


def test_names_and_addresses_never_pass_as_maker_or_model(helper):
    for bad in ("Juan's iPhone", "iPhone de Juan", "Juans-MacBook-Pro", "12345", "192.168.1.5", "aa:bb:cc:dd:ee:ff",
                "http://router.local", "nas.local", "Café TV", "juan@example.com", "", None, 7):
        assert helper._plain(bad, 60) is None, bad
    assert helper._plain("Brother Industries, Ltd.", 40) == "Brother"
    assert helper._plain("DocuPrint CP115/118 w", 60) == "DocuPrint CP115/118 w"
    assert helper._plain("A" * 30 + " " + "B" * 30, 40) == "A" * 30 + " " + "B" * 9  # cut to the limit
    mine = {}
    helper._keep(mine, {"maker": "Apple", "model": "Juan's iPhone"})
    assert mine == {"maker": "Apple"}
    helper._keep(mine, {"maker": "FUJI XEROX", "model": "FUJI XEROX DocuPrint CP115"})
    assert mine == {"maker": "FUJI XEROX", "model": "DocuPrint CP115"}


def test_found_things_carry_maker_and_model_but_no_address(helper, monkeypatch):
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d", "netKey": KEY})
    monkeypatch.setattr(helper, "_neighbours", lambda: {"192.168.1.1": "24:a4:3c:11:22:33"})
    monkeypatch.setattr(helper, "_open_ports", lambda ips: {"192.168.1.1": [80]})
    monkeypatch.setattr(helper, "_mdns_records", lambda seconds=None: [
        ("192.168.1.40", "_ipp._tcp", {"ty": "Brother HL-L2350DW"}),
        ("192.168.1.50", "_airplay._tcp", {"model": "Juan's iPhone"})])
    monkeypatch.setattr(helper, "_router_about", lambda budget: ("192.168.1.1", helper._upnp_about(DESCRIPTION)))
    sent = []
    monkeypatch.setattr(helper, "_post", lambda url, body, headers=None: sent.append(body) or (200, {"ok": True}))
    helper.discover(yes=True, quiet=True)
    items = sorted(sent[0]["items"], key=lambda i: i["guess"])
    assert [(i["guess"], i.get("maker"), i.get("model")) for i in items] == [
        ("Printer", "Brother", "HL-L2350DW"), ("Router", "NETGEAR", "Nighthawk R7000"),
        ("Speaker or TV", None, None)]
    assert "router" in items[1]["services"]
    text = json.dumps(sent)
    assert "192.168" not in text and "Juan" not in text and "24:a4" not in text


IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tinet 192.168.1.5 netmask 0xffffff00 broadcast 192.168.1.255
""" + "".join(f"bridge{i}: flags=8863<UP>\n\tinet 10.{i}.0.1 netmask 0xffffff00\n" for i in range(10)) + \
    "utun9: flags=8051<UP>\n\tinet 100.101.102.103 --> 100.101.102.103 netmask 0xffffffff\n"


def test_a_helper_reports_all_its_own_addresses_as_fingerprints(helper, monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: IFCONFIG if cmd == ["ifconfig"] else "")
    monkeypatch.setattr(helper, "_own_ip", lambda: "10.3.0.1")
    ips = helper._own_ips()
    assert ips[0] == "10.3.0.1" and "192.168.1.5" in ips and len(ips) == helper.SELVES == 8
    assert "127.0.0.1" not in ips and "100.101.102.103" not in ips  # loopback and shared addresses say nothing
    monkeypatch.setattr(helper.sys, "platform", "linux")
    monkeypatch.setattr(helper.shutil, "which", lambda n: "/usr/sbin/ip")
    monkeypatch.setattr(helper, "_run", lambda cmd, timeout=20: (
        "1: lo    inet 127.0.0.1/8 scope host lo\n2: eth0    inet 192.168.1.20/24 brd 192.168.1.255 scope global eth0\n"
        "3: wlan0    inet 192.168.1.21/24 scope global wlan0\n") if cmd[:3] == ["ip", "-4", "-o"] else "")
    monkeypatch.setattr(helper, "_own_ip", lambda: "192.168.1.20")
    assert helper._own_ips() == ["192.168.1.20", "192.168.1.21"]
    helper._save_config({"api": "https://api.example.com", "token": "t" * 43, "deviceId": "d", "netKey": KEY})
    monkeypatch.setattr(helper, "_relied_on", lambda budget=10: [("192.168.1.21", "service:445")])
    monkeypatch.setattr(helper, "_gateway", lambda: "192.168.1.1")
    net = helper._net()
    assert net["self"] == helper.net_tag(KEY, "192.168.1.20")
    assert net["selves"] == [helper.net_tag(KEY, "192.168.1.20"), helper.net_tag(KEY, "192.168.1.21")]
    assert net["peers"] == []  # a connection to its own other address is not something it relies on
    assert "192.168" not in json.dumps(net)
