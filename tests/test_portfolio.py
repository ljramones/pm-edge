from execution import KellyFractionalPortfolio, KellyPortfolioConfig
from strategies import EdgeSignal


def test_kelly_portfolio_respects_total_exposure() -> None:
    signals = [
        EdgeSignal(
            market_id=f"m-{index}",
            market_prob=0.45,
            model_prob=0.55,
            edge=0.10,
            confidence=0.8,
        )
        for index in range(10)
    ]
    allocator = KellyFractionalPortfolio(
        KellyPortfolioConfig(kelly_fraction=0.5, max_position_weight=0.1, max_total_exposure=0.2)
    )

    targets = allocator.allocate(signals, capital=10_000)

    assert targets
    assert sum(target.target_weight for target in targets) <= 0.2


def test_kelly_portfolio_penalizes_correlation() -> None:
    signals = [
        EdgeSignal(market_id="a", market_prob=0.45, model_prob=0.58, edge=0.13, confidence=0.8),
        EdgeSignal(market_id="b", market_prob=0.45, model_prob=0.58, edge=0.13, confidence=0.8),
    ]
    allocator = KellyFractionalPortfolio(KellyPortfolioConfig(correlation_penalty=0.5))

    plain = allocator.allocate(signals, capital=10_000)
    penalized = allocator.allocate(signals, capital=10_000, correlations={("a", "b"): 0.8})

    assert sum(item.target_weight for item in penalized) < sum(item.target_weight for item in plain)
