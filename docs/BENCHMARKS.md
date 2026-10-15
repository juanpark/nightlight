# Benchmarks

Measured 2026-10-15 19:26 UTC with `scripts/bench.py`: 5 runs of the demo story against the real model (`gemini-3.5-flash-lite`, thinking level MINIMAL, output cap 1024 tokens) on Google Agent Platform. Devices are the simulated sample home; Firestore was the local emulator, so network time to Firestore is not included. Prices: $0.3 / $2.5 per million input / output tokens (Agent Platform list price read 2026-10-16; thinking tokens bill as output).

Completed runs: 5 of 5. Failures: 0.

| Step | Median time to first words | Median full answer | 95th pct full answer | Model calls | Tool calls | Median cost |
|---|---|---|---|---|---|---|
| question | 3748 ms | 3750 ms | 4962 ms | 3 | 2 | $0.0010 |
| after approval | 1619 ms | 1621 ms | 1730 ms | 1 | 0 | $0.0001 |

Whole story (question + approval + follow-up): about **$0.0012** per run. Approve itself (one Firestore transaction): median 19 ms.

Worst case per model call under the enforced limits (16,000 input tokens, 1,024 output+thinking tokens): $0.00736; the $35 model budget covers 4,755 calls at the full worst-case reservation. Lower actual usage is refunded, which permits more calls, subject to the per-user, per-visitor and daily limits.

## History

| Date (UTC) | Setup | Question, median full answer | After approval | Story cost |
|---|---|---|---|---|
| 2026-10-15 18:39 | gemini-3.8-flash (low thinking); fleet listed by tool; follow-up with tools | 16.4 s (3 model calls) | 14.0 s (3 calls) | $0.0045 |
| 2026-10-15 19:26 UTC | gemini-3.5-flash-lite (minimal thinking); fleet summary in the instruction; one-call follow-up | 3.8 s | 1.6 s | $0.0012 |

## Raw runs

```json
{
 "rows": [
  {
   "run": 0,
   "step": "question",
   "wallMs": 5001.099125016481,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 2556,
   "tokensOut": 94,
   "tokensThinking": 0,
   "costUsd": 0.001002,
   "latencyMs": 4962,
   "firstTextMs": 4960
  },
  {
   "run": 0,
   "step": "after approval",
   "wallMs": 1592.9107919801027,
   "approveMs": 19.989917054772377,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 180,
   "tokensOut": 34,
   "tokensThinking": 0,
   "costUsd": 0.000139,
   "latencyMs": 1561,
   "firstTextMs": 1559
  },
  {
   "run": 1,
   "step": "question",
   "wallMs": 3496.870416915044,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 2556,
   "tokensOut": 92,
   "tokensThinking": 0,
   "costUsd": 0.000997,
   "latencyMs": 3468,
   "firstTextMs": 3467
  },
  {
   "run": 1,
   "step": "after approval",
   "wallMs": 1648.2392500620335,
   "approveMs": 14.372624922543764,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 178,
   "tokensOut": 32,
   "tokensThinking": 0,
   "costUsd": 0.000133,
   "latencyMs": 1621,
   "firstTextMs": 1619
  },
  {
   "run": 2,
   "step": "question",
   "wallMs": 3945.3085840214044,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 2556,
   "tokensOut": 109,
   "tokensThinking": 0,
   "costUsd": 0.001039,
   "latencyMs": 3912,
   "firstTextMs": 3910
  },
  {
   "run": 2,
   "step": "after approval",
   "wallMs": 1662.187207955867,
   "approveMs": 19.701584009453654,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 195,
   "tokensOut": 34,
   "tokensThinking": 0,
   "costUsd": 0.000143,
   "latencyMs": 1639,
   "firstTextMs": 1637
  },
  {
   "run": 3,
   "step": "question",
   "wallMs": 3435.3694589808583,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 2552,
   "tokensOut": 92,
   "tokensThinking": 0,
   "costUsd": 0.000996,
   "latencyMs": 3401,
   "firstTextMs": 3399
  },
  {
   "run": 3,
   "step": "after approval",
   "wallMs": 1555.9911669697613,
   "approveMs": 18.834874965250492,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 178,
   "tokensOut": 33,
   "tokensThinking": 0,
   "costUsd": 0.000136,
   "latencyMs": 1534,
   "firstTextMs": 1533
  },
  {
   "run": 4,
   "step": "question",
   "wallMs": 3781.421458115801,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 2557,
   "tokensOut": 109,
   "tokensThinking": 0,
   "costUsd": 0.00104,
   "latencyMs": 3750,
   "firstTextMs": 3748
  },
  {
   "run": 4,
   "step": "after approval",
   "wallMs": 1748.3149589970708,
   "approveMs": 17.936249962076545,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 195,
   "tokensOut": 34,
   "tokensThinking": 0,
   "costUsd": 0.000143,
   "latencyMs": 1730,
   "firstTextMs": 1729
  }
 ],
 "failures": []
}
```
