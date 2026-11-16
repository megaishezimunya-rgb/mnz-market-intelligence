"""Registry for the five independent MNZ market engines."""

from __future__ import annotations

from engines.commodities import ENGINE as COMMODITIES_ENGINE
from engines.crypto import ENGINE as CRYPTO_ENGINE
from engines.forex import ENGINE as FOREX_ENGINE
from engines.indices import ENGINE as INDICES_ENGINE
from engines.stocks import ENGINE as STOCKS_ENGINE
from engines.base import EngineContext, MarketEngine

ENGINES: dict[str, MarketEngine] = {
    engine.key: engine
    for engine in (FOREX_ENGINE, CRYPTO_ENGINE, STOCKS_ENGINE, COMMODITIES_ENGINE, INDICES_ENGINE)
}

ORDER = ["forex", "crypto", "stocks", "commodities", "indices"]


def get_engine(key: str) -> MarketEngine:
    """Return an engine by key, raising a clear error for unknown markets."""
    try:
        return ENGINES[key]
    except KeyError as exc:
        raise KeyError(f"Unknown market engine '{key}'. Available: {', '.join(ORDER)}") from exc


def all_engines() -> list[MarketEngine]:
    return [ENGINES[key] for key in ORDER]


__all__ = ["ENGINES", "ORDER", "get_engine", "all_engines", "EngineContext", "MarketEngine"]
