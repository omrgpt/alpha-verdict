# AlphaVerdict

**The point-in-time stock strategy research engine.**

AlphaVerdict turns user-owned stock data and one ranking strategy into three
auditable products:

1. a point-in-time daily screen;
2. a causal, cost-aware portfolio backtest;
3. an adversarial verdict with evidence and next validation work.

It does not place orders, hold broker credentials, choose a data provider, or
claim that historical results predict future returns.

## The invariant

At decision time *t*, strategy code receives only rows with a knowledge timestamp
at or before *t*. Historical fundamentals and events are filtered by
`available_at`; universe membership is filtered by both effective and knowledge
time. A strategy used for today’s screen is the same object evaluated in history.

## The workflow

```text
adapter → canonical bitemporal bundle → snapshot → strategy → screen/backtest
                                                        ↓
                                            deterministic audit council
                                                        ↓
                                        JSON + HTML + hash manifest
```

Start with the [quickstart](quickstart.md), then read the
[methodology](methodology.md) before interpreting a result.

!!! warning
    A verdict is a software research result. It is not investment advice, a
    recommendation, or authorization to risk capital.
