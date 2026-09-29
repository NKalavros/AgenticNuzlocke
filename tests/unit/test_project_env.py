"""`.env` fills unset keys and does not clobber the process environment."""

from __future__ import annotations

import os

from nuzlocke.config import ensure_relay_routing, load_project_env

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def _clear(monkeypatch, *names: str) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def _gost_listening(monkeypatch) -> None:
    monkeypatch.setattr("nuzlocke.config._local_port_open", lambda host, port: True)


def test_load_project_env_skips_existing_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("NUZLOCKE_TEST_ENV_KEY", "from-env")
    _clear(monkeypatch, "NUZLOCKE_TEST_NEW_KEY", "NUZLOCKE_TEST_QUOTED")
    path = tmp_path / ".env"
    path.write_text(
        '# comment\nNUZLOCKE_TEST_ENV_KEY="from-file"\n'
        "NUZLOCKE_TEST_NEW_KEY=value\n"
        'export NUZLOCKE_TEST_QUOTED="a b"\n',
        encoding="utf-8",
    )
    load_project_env(path)
    assert os.environ["NUZLOCKE_TEST_ENV_KEY"] == "from-env"
    assert os.environ["NUZLOCKE_TEST_NEW_KEY"] == "value"
    assert os.environ["NUZLOCKE_TEST_QUOTED"] == "a b"


def test_relay_routing_keeps_loopback_direct(monkeypatch):
    monkeypatch.setenv("NODE_OPTIONS", "")
    monkeypatch.setenv("NO_PROXY", "example.com")
    monkeypatch.setenv("no_proxy", "example.com")
    _clear(monkeypatch, "NODE_USE_ENV_PROXY", "NUZLOCKE_RELAY", *_PROXY_VARS)
    ensure_relay_routing()
    assert "NODE_USE_ENV_PROXY" not in os.environ
    for name in ("NO_PROXY", "no_proxy"):
        hosts = set(os.environ[name].split(","))
        assert "example.com" in hosts
        assert {"127.0.0.1", "localhost", "::1"} <= hosts


def test_relay_routing_leaves_gost_alone_unless_asked(monkeypatch):
    _clear(monkeypatch, "NUZLOCKE_RELAY", *_PROXY_VARS)
    monkeypatch.setenv("NODE_OPTIONS", "")
    _gost_listening(monkeypatch)
    ensure_relay_routing()
    assert "HTTPS_PROXY" not in os.environ
    assert "cursor_http2_proxy.cjs" not in os.environ.get("NODE_OPTIONS", "")


def test_relay_routing_fills_gost_when_asked(monkeypatch):
    _clear(monkeypatch, "NODE_USE_ENV_PROXY", *_PROXY_VARS)
    monkeypatch.setenv("NUZLOCKE_RELAY", "1")
    monkeypatch.setenv("NODE_OPTIONS", "")
    _gost_listening(monkeypatch)
    ensure_relay_routing()
    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:9999"
    assert os.environ["ALL_PROXY"] == "http://127.0.0.1:9999"
    assert os.environ["NODE_USE_ENV_PROXY"] == "1"
    assert "cursor_http2_proxy.cjs" in os.environ["NODE_OPTIONS"]


def test_relay_routing_does_not_replace_an_existing_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://example:1")
    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=512")
    _gost_listening(monkeypatch)
    ensure_relay_routing()
    assert os.environ["HTTPS_PROXY"] == "http://example:1"
    assert os.environ["NODE_OPTIONS"].startswith("--max-old-space-size=512 ")
    assert "cursor_http2_proxy.cjs" in os.environ["NODE_OPTIONS"]
    ensure_relay_routing()
    assert os.environ["NODE_OPTIONS"].count("cursor_http2_proxy.cjs") == 1
