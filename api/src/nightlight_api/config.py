"""Settings read from the environment. No secrets live in code."""

import os
import re
from dataclasses import dataclass, field


def _list(name: str, default: str = "") -> list[str]:
    return [v for v in re.split(r"[,\s]+", os.environ.get(name, default)) if v]


def passkey_origin_ok(origin: str) -> bool:
    return origin == settings.app_url or origin.startswith(("http://localhost:", "http://127.0.0.1:"))


@dataclass
class Settings:
    project_id: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "demo-nightlight")
    port: int = int(os.environ.get("PORT", "8080"))
    web_origins: list[str] = field(default_factory=lambda: _list("WEB_ORIGINS", "http://localhost:3000"))
    # The app people use (install lines, links in answers). Other web origins (local dev, previews) may call the API
    # but are never handed out, and passkeys for expert sessions are made only here or on a local dev server.
    app_url: str = os.environ.get("APP_URL", "http://localhost:3000")
    # Reset barrier lease and batch size.
    reset_lease_seconds: int = int(os.environ.get("RESET_LEASE_SECONDS", "60"))
    reset_batch_size: int = int(os.environ.get("RESET_BATCH_SIZE", "20"))
    # Trust: clean human-approved runs needed before a promotion offer.
    promotion_threshold: int = 3

    # Model and cost guards (build plan §7). Default: Gemini 3.8 Flash at low thinking (it rejects minimal), chosen 18
    # Oct on measured reliability: the same 12 demo questions, 3 runs each, passed 26 of 36 on 3.5 Flash-Lite and 34 of
    # 35 on 3.8 Flash, at about twice the time per answer (median 9.0 s vs 4.6 s) and 2.5 times the cost ($0.016 vs
    # $0.0065). Prices: Agent Platform global list price per 1M tokens (3.5 Flash-Lite $0.30 / $2.50; 3.8 Flash
    # $0.75 / $3.75), read 2026-10-16.
    model: str = os.environ.get("MODEL", "gemini-3.8-flash")
    thinking_level: str = os.environ.get("THINKING_LEVEL", "LOW")
    price_in_per_m: float = float(os.environ.get("PRICE_IN_PER_M", "0.75"))
    price_out_per_m: float = float(os.environ.get("PRICE_OUT_PER_M", "3.75"))
    max_input_tokens: int = int(os.environ.get("MAX_INPUT_TOKENS", "16000"))
    # Enforced by the API as a hard cap on output + thinking tokens combined (verified 2026-10-16).
    max_output_tokens: int = int(os.environ.get("MAX_OUTPUT_TOKENS", "1024"))
    model_budget_usd: float = float(os.environ.get("MODEL_BUDGET_USD", "35"))
    model_calls_per_uid_hour: int = int(os.environ.get("MODEL_CALLS_PER_UID_HOUR", "120"))
    model_calls_per_ip_hour: int = int(os.environ.get("MODEL_CALLS_PER_IP_HOUR", "100"))
    model_calls_per_day: int = int(os.environ.get("MODEL_CALLS_PER_DAY", "2000"))
    turns_per_uid_hour: int = int(os.environ.get("TURNS_PER_UID_HOUR", "40"))
    model_calls_per_turn: int = 8  # an investigation: look, measure, maybe look again, then answer
    tool_calls_per_turn: int = 8
    kill_switch: bool = os.environ.get("MODEL_KILL_SWITCH", "0") == "1"
    ip_hash_salt: str = os.environ.get("IP_HASH_SALT", "nightlight")
    # Turn leases.
    turn_lease_seconds: int = int(os.environ.get("TURN_LEASE_SECONDS", "60"))
    history_messages: int = 20
    history_chars: int = 12000
    tool_result_bytes: int = 4000
    # Memory Bank (Agent Platform). Empty id = memory off: every memory call is a no-op, so tests and local runs need
    # no cloud. The id is the last segment of the Memory Bank's resource name (.../reasoningEngines/<id>).
    memory_bank_id: str = os.environ.get("MEMORY_BANK_ID", "")
    # The scheduled sweep (`POST /internal/sweep`) must carry a Google identity token for this audience and account.
    sweep_audience: str = os.environ.get("SWEEP_AUDIENCE", "")
    sweep_invoker: str = os.environ.get("SWEEP_INVOKER", "")
    # Live demo machines (live.py). LIVE_POOL="nl-live-1=judge-pool-1,..." (instance=pool account uid); empty = off.
    live_pool: list[str] = field(default_factory=lambda: _list("LIVE_POOL"))
    live_zone: str = os.environ.get("LIVE_ZONE", "asia-northeast3-a")
    live_idle_seconds: int = int(os.environ.get("LIVE_IDLE_SECONDS", "900"))  # no heartbeat this long: released
    live_max_seconds: int = int(os.environ.get("LIVE_MAX_SECONDS", "3600"))  # hard cap on one lease
    live_per_ip: int = int(os.environ.get("LIVE_PER_IP", "2"))  # live leases one visitor address may hold at once
    live_admissions_per_hour: int = int(os.environ.get("LIVE_ADMISSIONS_PER_HOUR", "4"))  # new leases per address
    live_resets_per_lease: int = int(os.environ.get("LIVE_RESETS_PER_LEASE", "3"))  # Start fresh, per visit
    live_eta_seconds: int = int(os.environ.get("LIVE_ETA_SECONDS", "60"))  # measured click-to-ready 48-59 s (18 Oct)
    live_restore_seconds: int = int(os.environ.get("LIVE_RESTORE_SECONDS", "120"))  # Start fresh, click-to-ready 105-110 s (18 Oct)
    # The service account that signs pool custom tokens through IAM signBlob (needs Token Creator on itself).
    live_signer: str = os.environ.get("LIVE_SIGNER", "")
    memory_location: str = os.environ.get("MEMORY_BANK_LOCATION", "global")
    memory_fact_chars: int = 300
    release_dir: str = os.environ.get("RELEASE_DIR", "")  # the signed helper on offer (default: package "release/")
    memory_recall_seconds: float = 3.0
    memory_write_seconds: float = 10.0

    # Investigate mode: a stronger model that thinks longer and may take many more steps (the person chose it).
    deep_model: str = os.environ.get("DEEP_MODEL", "gemini-3.8-flash")
    deep_thinking: str = os.environ.get("DEEP_THINKING", "MEDIUM")  # HIGH took up to 2 minutes for a first word
    deep_price_in_per_m: float = float(os.environ.get("DEEP_PRICE_IN_PER_M", "0.75"))
    deep_price_out_per_m: float = float(os.environ.get("DEEP_PRICE_OUT_PER_M", "3.75"))
    deep_max_output_tokens: int = int(os.environ.get("DEEP_MAX_OUTPUT_TOKENS", "4096"))
    deep_calls_per_turn: int = int(os.environ.get("DEEP_CALLS_PER_TURN", "24"))
    # Input ceiling per Investigate call. Measured 18 Oct: instruction + 31 tool declarations = 4.3k tokens, plus the
    # home summary, memories and up to history_chars of chat (~3k) = about 9k before the turn's own steps; one full
    # tool result (tool_result_bytes) is ~1-1.3k tokens. 16k left room for ~5 full steps of the 24 allowed; 24k holds
    # ~12, and older ones are shortened in the request (agent.bound_input). Worst case reserved per call goes from
    # $0.027 to $0.033 (deep_c_max), so the budget reservation stays exact.
    deep_max_input_tokens: int = int(os.environ.get("DEEP_MAX_INPUT_TOKENS", "24000"))
    deep_turn_seconds: int = int(os.environ.get("DEEP_TURN_SECONDS", "240"))
    quick_turn_seconds: int = int(os.environ.get("QUICK_TURN_SECONDS", "120"))
    # A model call that sends nothing at all for this long is cancelled and retried once (Agent Platform has a
    # latency tail: single Quick calls of 30-60 s with no thinking, where the usual call takes 2-5 s).
    call_gap_seconds: float = float(os.environ.get("CALL_GAP_SECONDS", "30"))
    deep_call_gap_seconds: float = float(os.environ.get("DEEP_CALL_GAP_SECONDS", "45"))

    @property
    def deep_c_max(self) -> float:
        return (self.deep_max_input_tokens * self.deep_price_in_per_m
                + self.deep_max_output_tokens * self.deep_price_out_per_m) / 1e6

    @property
    def c_max(self) -> float:
        """Worst-case dollar cost of one model call under the enforced limits."""
        return (self.max_input_tokens * self.price_in_per_m + self.max_output_tokens * self.price_out_per_m) / 1e6


settings = Settings()
