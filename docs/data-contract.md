# Data contract

AlphaVerdict owns schemas, not data. A provider adapter must return a `DataBundle`
whose rows identify their source and whose timestamps preserve what was knowable at
each historical decision.

All timestamps are normalized to UTC. Symbols are stripped and uppercased. Duplicate
temporal keys are rejected rather than silently resolved.

One run assumes a coherent daily session index. A single exchange or aligned regional
universe works through supplied data; mixed exchanges with different holiday calendars
need an explicit alignment policy and are not yet first-class.

## Prices

| Column | Meaning |
|---|---|
| `symbol` | canonical stock identifier chosen by the user |
| `timestamp` | daily session timestamp |
| `open`, `high`, `low`, `close` | numeric OHLC values |
| `volume` | numeric volume; missing is permitted, negative is audited |
| `source` | provider or transformation lineage |

The adapter must declare its adjustment policy in
`metadata["price_adjustment"]`. “Adjusted” is not precise enough: document whether
opens and closes are split-adjusted, dividend-adjusted, or raw, and how delisted
securities are represented.

## Features

```text
symbol,observed_at,available_at,feature,value,source,revision
```

- `observed_at` is when the underlying fact economically applies—for example, a
  fiscal quarter end.
- `available_at` is when the strategy could actually know it—for example, the
  filing publication timestamp.
- `revision` preserves restatements or vendor revisions as separate observations.

The snapshot selects rows where both timestamps are no later than the decision and
then chooses the latest observed/available/revision tuple for each feature. Never
backfill a later revision into earlier snapshots.

## Events

```text
symbol,event_at,available_at,event_type,payload,source
```

`payload` is a JSON object. It can carry a news sentiment score, filing metadata,
scheduled event attributes, or another bounded record. A scheduled future event may
be known now, but `known_events()` excludes future `event_at` values unless strategy
code opts in explicitly.

For LLM-derived historical labels, `available_at` alone does not solve parametric
look-ahead: a present-day model may remember later outcomes. Either use a model whose
training cutoff predates the event, preserve contemporaneous archived outputs, or
treat the result as contaminated and disclose it.

## Universe membership

```text
symbol,effective_from,effective_to,available_at,source
```

`effective_to` is exclusive and nullable. An active stock at decision time *t* must
satisfy:

```text
available_at <= t
effective_from <= t
effective_to is null OR effective_to > t
```

Set `metadata["survivorship"] = "point_in_time"` only when membership and relevant
delistings are genuinely represented. If no universe table exists, AlphaVerdict
falls back to symbols with a price on the latest known session and raises a
survivorship finding during audit.

## Identity and lineage

`DataBundle.fingerprint()` hashes normalized schemas, row content, and metadata.
Row order does not affect the digest. Changing a value, timestamp, source, or policy
does. The hash is stored in every screen and run manifest.

## Adapter conformance checklist

- [ ] Timestamps are UTC and mean what the schema says.
- [ ] Symbols are stable through mergers, share-class changes, and delistings.
- [ ] Every row has non-empty source lineage.
- [ ] Corporate-action policy is declared and tested against known cases.
- [ ] Revisions are not collapsed backward in time.
- [ ] Universe history does not use today’s constituents for old dates.
- [ ] Licensed data stays outside the public repository.
- [ ] Missing observations remain missing; they are never backward-filled from the future.
