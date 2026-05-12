from datetime import UTC, datetime

from data.poll_aggregator import PollAggregator


def test_poll_aggregator_normalizes_and_weights_records() -> None:
    aggregator = PollAggregator()
    records = aggregator.normalize_records(
        [
            {
                "event_slug": "election-2028",
                "pollster": "Example Polls",
                "grade": "A",
                "sample_size": 1200,
                "end_date": "2026-05-01T00:00:00+00:00",
                "answers": [
                    {"candidate": "Yes", "support": 54},
                    {"candidate": "No", "support": 46},
                ],
            }
        ]
    )

    aggregates = aggregator.aggregate(records, as_of=datetime(2026, 5, 2, tzinfo=UTC))

    assert len(records) == 2
    assert aggregates[0].poll_count == 1
    assert {aggregate.candidate for aggregate in aggregates} == {"Yes", "No"}
    assert max(aggregate.probability for aggregate in aggregates) == 0.54
