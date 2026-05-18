"""
DentEdTech-ScopingReviewer™ — API Client Manager
============================================
Manages multiple Anthropic API keys, each bound to a specialised role.

Why multiple keys?
------------------
1. **Rate-limit parallelism** — each key has its own bucket, so heavy
   drafting work doesn't starve quick extraction calls.
2. **Cost isolation** — you can see at a glance which workload (drafting,
   critique, extraction) is burning tokens.
3. **Fault tolerance** — if any key trips a 429 or 529, we transparently
   fall back to the spare without losing the in-progress section.
4. **Model specialisation** — different roles can pin different models
   (e.g. Haiku for cheap extraction passes, Opus for critique).

Roles
-----
    primary      — orchestration, planning, final assembly
    extraction   — parsing uploaded PDFs, charting study attributes
    critique     — originality audits, coherence, section-level rigour
    drafting     — section prose generation (highest token spend)
    fallback     — hot spare for rate-limit overflow

The Orchestrator (`app/agents/orchestrator.py`) is the only module that
should reach into this manager directly. All other agents request their
client via the orchestrator, so policy stays in one place.

Model-specific parameter handling
---------------------------------
Some Claude models deprecate sampling parameters that older ones accept.
We detect these and strip the unsupported parameters silently:
  - Opus 4.7+ : temperature, top_p, top_k all deprecated (model handles
                its own sampling internally).
  - Earlier models : accept these parameters normally.

Adding a new model with parameter restrictions is one line in
`MODELS_WITHOUT_TEMPERATURE` below.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from anthropic import Anthropic, APIError, RateLimitError
from anthropic.types import Message
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model capability matrix
# ---------------------------------------------------------------------------
# Models that have deprecated `temperature`, `top_p`, and `top_k` — the
# model handles its own sampling internally and the API rejects any of
# these parameters with a 400 invalid_request_error.
#
# This list is checked by substring match so new Opus 4.7 variants
# (e.g. claude-opus-4-7-thinking-2025-XX-XX) are handled automatically.
# ---------------------------------------------------------------------------
MODELS_WITHOUT_TEMPERATURE: tuple[str, ...] = (
    "claude-opus-4-7",
)


def _model_accepts_temperature(model: str) -> bool:
    """Return False if the given model rejects the `temperature` parameter."""
    if not model:
        return True
    return not any(marker in model for marker in MODELS_WITHOUT_TEMPERATURE)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role(str, Enum):
    """Specialised role each API key is bound to."""

    PRIMARY = "primary"
    EXTRACTION = "extraction"
    CRITIQUE = "critique"
    DRAFTING = "drafting"
    FALLBACK = "fallback"


# ---------------------------------------------------------------------------
# Per-role configuration
# ---------------------------------------------------------------------------
@dataclass
class RoleConfig:
    """
    Configuration bound to a single role.

    Each role can use a different model (e.g. Haiku for cheap extraction,
    Opus for critique work where reasoning quality matters most).
    """

    env_var: str
    model: str
    max_tokens: int
    temperature: float
    description: str

    api_key: Optional[str] = field(default=None, init=False)
    client: Optional[Anthropic] = field(default=None, init=False)

    def is_available(self) -> bool:
        return bool(self.api_key)


# ---------------------------------------------------------------------------
# Default role policy
# ---------------------------------------------------------------------------
# Tuned for PRISMA-ScR work specifically:
#   - extraction runs cheap & fast (lots of small PDF passes)
#   - critique runs expensive & careful (low temperature, high tokens)
#   - drafting balances both
#
# Note: `temperature` values on Opus 4.7 roles are configured for
# documentation but are silently stripped at request time.
# ---------------------------------------------------------------------------
DEFAULT_ROLE_POLICY: dict[Role, RoleConfig] = {
    Role.PRIMARY: RoleConfig(
        env_var="ANTHROPIC_API_KEY_PRIMARY",
        model="claude-opus-4-7",
        max_tokens=4096,
        temperature=0.2,
        description="Orchestration, planning, final assembly",
    ),
    Role.EXTRACTION: RoleConfig(
        env_var="ANTHROPIC_API_KEY_EXTRACTION",
        model="claude-haiku-4-5-20251001",
        max_tokens=8192,
        temperature=0.0,
        description="PDF parsing, attribute charting",
    ),
    Role.CRITIQUE: RoleConfig(
        env_var="ANTHROPIC_API_KEY_CRITIQUE",
        model="claude-opus-4-7",
        max_tokens=8192,
        temperature=0.1,
        description="Originality + coherence audits",
    ),
    Role.DRAFTING: RoleConfig(
        env_var="ANTHROPIC_API_KEY_DRAFTING",
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0.3,
        description="Section prose generation",
    ),
    Role.FALLBACK: RoleConfig(
        env_var="ANTHROPIC_API_KEY_FALLBACK",
        model="claude-sonnet-4-6",
        max_tokens=8192,
        temperature=0.2,
        description="Hot spare for rate-limit overflow",
    ),
}


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------
class APIClientManager:
    """
    Central manager for role-bound Anthropic clients.

    Usage
    -----
        manager = APIClientManager()
        response = manager.complete(
            role=Role.EXTRACTION,
            system="You are a PRISMA-ScR data extractor...",
            messages=[{"role": "user", "content": "Extract from..."}],
        )
    """

    def __init__(
        self,
        policy: Optional[dict[Role, RoleConfig]] = None,
        allow_single_key_mode: bool = True,
    ):
        """
        Parameters
        ----------
        policy
            Override default role configuration.
        allow_single_key_mode
            If only PRIMARY is set, route every role through it.
            Useful during development before you've provisioned all keys.
        """
        self.policy = policy or DEFAULT_ROLE_POLICY
        self.allow_single_key_mode = allow_single_key_mode
        self._load_keys()
        self._build_clients()
        self._log_status()

    # -- setup -------------------------------------------------------------
    def _load_keys(self) -> None:
        for role, cfg in self.policy.items():
            cfg.api_key = os.getenv(cfg.env_var)

    def _build_clients(self) -> None:
        for role, cfg in self.policy.items():
            if cfg.is_available():
                cfg.client = Anthropic(api_key=cfg.api_key)

        # Single-key mode: route everything through PRIMARY.
        primary = self.policy[Role.PRIMARY]
        if self.allow_single_key_mode and primary.is_available():
            for role, cfg in self.policy.items():
                if not cfg.is_available():
                    cfg.client = primary.client
                    cfg.api_key = primary.api_key
                    logger.info(
                        "Role %s falling back to PRIMARY key (single-key mode).",
                        role.value,
                    )

    def _log_status(self) -> None:
        available = [r.value for r, c in self.policy.items() if c.client]
        missing = [r.value for r, c in self.policy.items() if not c.client]
        logger.info("API clients ready for roles: %s", available)
        if missing:
            logger.warning("Roles without a key (will fail on call): %s", missing)

    # -- public API --------------------------------------------------------
    def get_config(self, role: Role) -> RoleConfig:
        cfg = self.policy[role]
        if cfg.client is None:
            raise RuntimeError(
                f"No API key configured for role '{role.value}'. "
                f"Set {cfg.env_var} in your .env file."
            )
        return cfg

    def complete(
        self,
        role: Role,
        system: str,
        messages: list[dict],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
        max_retries: int = 2,
        allow_fallback: bool = True,
    ) -> Message:
        """
        Run a completion using the client bound to the given role.

        Strips `temperature` automatically for models that have deprecated
        it (e.g. Opus 4.7). Falls back to the FALLBACK key on rate-limit /
        overload after the primary attempt is exhausted.
        """
        cfg = self.get_config(role)
        attempts = 0
        chosen_model = model or cfg.model

        # Build the kwargs once, omitting temperature for models that
        # reject it. This is the fix for the Opus 4.7 deprecation.
        call_kwargs: dict[str, Any] = {
            "model": chosen_model,
            "max_tokens": max_tokens or cfg.max_tokens,
            "system": system,
            "messages": messages,
        }
        if _model_accepts_temperature(chosen_model):
            call_kwargs["temperature"] = (
                temperature if temperature is not None else cfg.temperature
            )
        else:
            logger.debug(
                "Model %s does not accept temperature — omitting parameter.",
                chosen_model,
            )

        while True:
            try:
                return cfg.client.messages.create(**call_kwargs)

            except RateLimitError as e:
                attempts += 1
                logger.warning(
                    "Rate limit on role %s (attempt %d/%d): %s",
                    role.value,
                    attempts,
                    max_retries,
                    e,
                )
                if attempts > max_retries:
                    if allow_fallback and role != Role.FALLBACK:
                        logger.info(
                            "Switching role %s → FALLBACK after rate limit.",
                            role.value,
                        )
                        return self.complete(
                            role=Role.FALLBACK,
                            system=system,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            model=model,
                            max_retries=max_retries,
                            allow_fallback=False,
                        )
                    raise
                time.sleep(2 ** attempts)

            except APIError as e:
                # 529 overloaded → retry; everything else bubbles up.
                if getattr(e, "status_code", None) == 529 and attempts < max_retries:
                    attempts += 1
                    logger.warning("API overloaded, retrying (%d/%d).",
                                   attempts, max_retries)
                    time.sleep(2 ** attempts)
                    continue
                raise

    # -- diagnostics -------------------------------------------------------
    def status_report(self) -> dict[str, dict]:
        """Lightweight introspection for the Streamlit sidebar."""
        return {
            role.value: {
                "configured": cfg.is_available(),
                "model": cfg.model,
                "description": cfg.description,
                "accepts_temperature": _model_accepts_temperature(cfg.model),
            }
            for role, cfg in self.policy.items()
        }


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------
_manager_instance: Optional[APIClientManager] = None


def get_manager() -> APIClientManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = APIClientManager()
    return _manager_instance
