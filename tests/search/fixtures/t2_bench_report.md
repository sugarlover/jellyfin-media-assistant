# D8 Benchmarks — phonetic-aware shortlisting vs baseline

## real (8464 items)

- Build time: **611.2 ms**
- Peak memory: **58.49 MB**

| Query | Latency (ms, median of 20, warm) |
|---|---|
| `Your Idol` | 1.394 |
| `your idle` | 33.924 |
| `You're idol` | 61.522 |
| `You're idle` | 61.935 |
| `you re idle` | 43.013 |

## synthetic (10000 items)

- Build time: **858.4 ms**
- Peak memory: **74.4 MB**

| Query | Latency (ms, median of 20, warm) |
|---|---|
| `Your Idol` | 16.836 |
| `your idle` | 9.798 |
| `You're idol` | 71.407 |
| `You're idle` | 72.466 |
| `you re idle` | 45.01 |

