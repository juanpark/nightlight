# Benchmarks

Measured 2026-10-16 11:07 UTC with `scripts/bench.py`: 6 runs of the demo story against the real model (`gemini-3.5-flash-lite`, thinking level LOW, output cap 1024 tokens) on Google Agent Platform. Devices are the simulated sample home; Firestore was the local emulator, so network time to Firestore is not included. Prices: $0.3 / $2.5 per million input / output tokens (Agent Platform list price read 2026-10-16; thinking tokens bill as output).

Completed runs: 6 of 6. Failures: 0.

| Step | Median time to first words | Median full answer | 95th pct full answer | Model calls | Tool calls | Median cost |
|---|---|---|---|---|---|---|
| question | 5152 ms | 5154 ms | 5641 ms | 3 | 2 | $0.0029 |
| after approval | 2054 ms | 2056 ms | 2693 ms | 1 | 0 | $0.0006 |

Whole story (question + approval + follow-up): about **$0.0036** per run. Approve itself (one Firestore transaction): median 20 ms.

Worst case per model call under the enforced limits (16,000 input tokens, 1,024 output+thinking tokens): $0.00736; the $35 model budget covers 4,755 calls at the full worst-case reservation. Lower actual usage is refunded, which permits more calls, subject to the per-user, per-visitor and daily limits.

## History

Minimal thinking was faster, but once real devices, memory and more tools were added it proposed the fix card in
only 1–2 of 6 live runs (it asked in words instead), so the default moved to low thinking (6 of 6).

| Date (UTC) | Setup | Question, median full answer | After approval | Story cost |
|---|---|---|---|---|
| 2026-10-15 18:39 | gemini-3.8-flash (low thinking); fleet listed by tool; follow-up with tools | 16.4 s (3 model calls) | 14.0 s (3 calls) | $0.0045 |
| 2026-10-15 19:26 | gemini-3.5-flash-lite (minimal thinking); fleet summary in the instruction; one-call follow-up | 3.8 s | 1.6 s | $0.0012 |
| 2026-10-16 11:07 UTC | gemini-3.5-flash-lite (low thinking); fleet summary in the instruction; one-call follow-up | 5.2 s | 2.1 s | $0.0036 |

## Raw runs

```json
{
 "rows": [
  {
   "run": 0,
   "step": "question",
   "wallMs": 5680.942333070561,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 6575,
   "tokensOut": 89,
   "tokensThinking": 254,
   "costUsd": 0.00283,
   "latencyMs": 5641,
   "firstTextMs": 5639
  },
  {
   "run": 0,
   "step": "after approval",
   "wallMs": 1642.322292085737,
   "approveMs": 23.474792018532753,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 229,
   "tokensOut": 32,
   "tokensThinking": 0,
   "costUsd": 0.000149,
   "latencyMs": 1607,
   "firstTextMs": 1605
  },
  {
   "run": 1,
   "step": "question",
   "wallMs": 4330.238958122209,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 6469,
   "tokensOut": 102,
   "tokensThinking": 209,
   "costUsd": 0.002718,
   "latencyMs": 4294,
   "firstTextMs": 4292
  },
  {
   "run": 1,
   "step": "after approval",
   "wallMs": 2424.4652087800205,
   "approveMs": 18.65383400581777,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 242,
   "tokensOut": 34,
   "tokensThinking": 318,
   "costUsd": 0.000953,
   "latencyMs": 2395,
   "firstTextMs": 2393
  },
  {
   "run": 2,
   "step": "question",
   "wallMs": 5119.360541924834,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 6594,
   "tokensOut": 88,
   "tokensThinking": 328,
   "costUsd": 0.003018,
   "latencyMs": 5087,
   "firstTextMs": 5084
  },
  {
   "run": 2,
   "step": "after approval",
   "wallMs": 2717.7024998236448,
   "approveMs": 24.11833289079368,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 228,
   "tokensOut": 39,
   "tokensThinking": 403,
   "costUsd": 0.001173,
   "latencyMs": 2693,
   "firstTextMs": 2692
  },
  {
   "run": 3,
   "step": "question",
   "wallMs": 5253.137458115816,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 6894,
   "tokensOut": 84,
   "tokensThinking": 411,
   "costUsd": 0.003306,
   "latencyMs": 5222,
   "firstTextMs": 5220
  },
  {
   "run": 3,
   "step": "after approval",
   "wallMs": 2696.8815410509706,
   "approveMs": 20.70320793427527,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 224,
   "tokensOut": 31,
   "tokensThinking": 399,
   "costUsd": 0.001142,
   "latencyMs": 2672,
   "firstTextMs": 2670
  },
  {
   "run": 4,
   "step": "question",
   "wallMs": 5618.798334151506,
   "modelCalls": 4,
   "toolCalls": 3,
   "tokensIn": 9766,
   "tokensOut": 109,
   "tokensThinking": 329,
   "costUsd": 0.004025,
   "latencyMs": 5586,
   "firstTextMs": 5584
  },
  {
   "run": 4,
   "step": "after approval",
   "wallMs": 1604.1992080863565,
   "approveMs": 19.48079210706055,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 229,
   "tokensOut": 38,
   "tokensThinking": 0,
   "costUsd": 0.000164,
   "latencyMs": 1573,
   "firstTextMs": 1571
  },
  {
   "run": 5,
   "step": "question",
   "wallMs": 3332.1462080348283,
   "modelCalls": 2,
   "toolCalls": 1,
   "tokensIn": 3991,
   "tokensOut": 78,
   "tokensThinking": 227,
   "costUsd": 0.00196,
   "latencyMs": 3303,
   "firstTextMs": 3301
  },
  {
   "run": 5,
   "step": "after approval",
   "wallMs": 1735.699708107859,
   "approveMs": 15.498458873480558,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 228,
   "tokensOut": 38,
   "tokensThinking": 0,
   "costUsd": 0.000163,
   "latencyMs": 1717,
   "firstTextMs": 1715
  }
 ],
 "failures": []
}
```
