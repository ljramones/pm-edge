from __future__ import annotations

import pandas as pd

from scripts.backfill_polymarket import (
    clob_tokens_with_outcomes,
    market_identifier,
    markets_to_resolved_frame,
    parse_markets_page,
    price_history_rows,
    tag_slug,
)


def test_parse_markets_page_accepts_keyset_response() -> None:
    markets, cursor = parse_markets_page({"markets": [{"id": "1"}], "next_cursor": "abc"})

    assert markets == [{"id": "1"}]
    assert cursor == "abc"


def test_resolved_market_frame_flattens_jsonish_fields() -> None:
    frame = markets_to_resolved_frame(
        [
            {
                "id": "m1",
                "question": "Will BTC close above 100k?",
                "closed": True,
                "category": "crypto",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["1", "0"]',
                "clobTokenIds": '["yes-token", "no-token"]',
                "tags": [{"slug": "crypto"}],
                "volumeNum": 123.4,
                "liquidityNum": "56.7",
            }
        ]
    )

    assert isinstance(frame, pd.DataFrame)
    assert frame.loc[0, "market_id"] == "m1"
    assert frame.loc[0, "winning_outcome"] == "Yes"
    assert frame.loc[0, "yes_price"] == 1.0
    assert frame.loc[0, "tags"] == ["crypto"]


def test_clob_token_pairing_and_identifier_helpers() -> None:
    market = {
        "conditionId": "condition/1",
        "outcomes": '["Yes", "No"]',
        "clobTokenIds": '["a", "b"]',
    }

    assert market_identifier(market) == "condition_1"
    assert clob_tokens_with_outcomes(market) == [("a", "Yes"), ("b", "No")]
    assert tag_slug("Crypto Markets") == "crypto-markets"


def test_price_history_rows_parses_clob_history_payload() -> None:
    rows = price_history_rows(
        {
            "market_id": "m1",
            "token_id": "yes-token",
            "outcome": "Yes",
            "source": "clob",
            "payload": {"history": [{"t": 1_704_067_200, "p": 0.42}]},
        }
    )

    assert len(rows) == 1
    assert rows[0]["market_id"] == "m1"
    assert rows[0]["price"] == 0.42
