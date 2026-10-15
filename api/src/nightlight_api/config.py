"""Settings read from the environment. No secrets live in code."""

import os
import re
from dataclasses import dataclass, field


def _list(name: str, default: str = "") -> list[str]:
    return [v for v in re.split(r"[,\s]+", os.environ.get(name, default)) if v]


@dataclass(frozen=True)
class Settings:
    project_id: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "demo-nightlight")
    port: int = int(os.environ.get("PORT", "8080"))
    web_origins: list[str] = field(default_factory=lambda: _list("WEB_ORIGINS", "http://localhost:3000"))
    # Reset barrier lease and batch size.
    reset_lease_seconds: int = int(os.environ.get("RESET_LEASE_SECONDS", "60"))
    reset_batch_size: int = int(os.environ.get("RESET_BATCH_SIZE", "20"))
    # Trust: clean human-approved runs needed before a promotion offer.
    promotion_threshold: int = 3

    # Model and cost guards (build plan §7). Prices: Agent Platform list price per 1M tokens, read 2026-10-16.
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
    model_calls_per_turn: int = 6
    kill_switch: bool = os.environ.get("MODEL_KILL_SWITCH", "0") == "1"
    ip_hash_salt: str = os.environ.get("IP_HASH_SALT", "nightlight")
    # Turn leases.
    turn_lease_seconds: int = int(os.environ.get("TURN_LEASE_SECONDS", "60"))
    history_messages: int = 20
    history_chars: int = 12000
    tool_result_bytes: int = 4000

    @property
    def c_max(self) -> float:
        """Worst-case dollar cost of one model call under the enforced limits."""
        return (self.max_input_tokens * self.price_in_per_m + self.max_output_tokens * self.price_out_per_m) / 1e6


settings = Settings()
