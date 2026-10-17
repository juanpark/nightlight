# Benchmarks

Measured 2026-10-17 08:14 UTC with `scripts/bench.py`: 10 runs of the demo story against the real model (`gemini-3.5-flash-lite`, thinking level LOW, output cap 1024 tokens) on Google Agent Platform. Devices are the simulated sample home; Firestore was the local emulator, so network time to Firestore is not included. Prices: $0.3 / $2.5 per million input / output tokens (Agent Platform list price read 2026-10-16; thinking tokens bill as output).

Completed runs: 9 of 10. Failures: 1.

| Step | Median time to first words | Median full answer | 95th pct full answer | Model calls | Tool calls | Median cost |
|---|---|---|---|---|---|---|
| question | 6729 ms | 6730 ms | 8585 ms | 3 | 2 | $0.0062 |
| after approval | 2687 ms | 2688 ms | 4573 ms | 1 | 0 | $0.0002 |

Whole story (question + approval + follow-up): about **$0.0068** per run. Approve itself (one Firestore transaction): median 102 ms.

Worst case per model call under the enforced limits (16,000 input tokens, 1,024 output+thinking tokens): $0.00736; the $35 model budget covers 4,755 calls at the full worst-case reservation. Lower actual usage is refunded, which permits more calls, subject to the per-user, per-visitor and daily limits.

## History

| Date (UTC) | Setup | Question, median full answer | After approval | Story cost |
|---|---|---|---|---|
| 2026-10-15 18:39 | gemini-3.8-flash (low thinking); fleet listed by tool; follow-up with tools | 16.4 s (3 model calls) | 14.0 s (3 calls) | $0.0045 |
| 2026-10-17 08:14 UTC | gemini-3.5-flash-lite (low thinking); fleet summary in the instruction; one-call follow-up | 6.7 s | 2.7 s | $0.0068 |

## Raw runs

```json
{
 "rows": [
  {
   "run": 0,
   "step": "question",
   "wallMs": 8623.55608299913,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16236,
   "tokensOut": 107,
   "tokensThinking": 432,
   "costUsd": 0.006218,
   "latencyMs": 8585,
   "firstTextMs": 8583
  },
  {
   "run": 0,
   "step": "after approval",
   "wallMs": 2537.42158300156,
   "approveMs": 71.58520899974974,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 242,
   "tokensOut": 34,
   "tokensThinking": 0,
   "costUsd": 0.000158,
   "latencyMs": 2495,
   "firstTextMs": 2489
  },
  {
   "run": 1,
   "step": "question",
   "wallMs": 6691.116417001467,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16240,
   "tokensOut": 124,
   "tokensThinking": 419,
   "costUsd": 0.006229,
   "latencyMs": 6626,
   "firstTextMs": 6618
  },
  {
   "run": 1,
   "step": "after approval",
   "wallMs": 4619.638166997902,
   "approveMs": 156.78429199761013,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 258,
   "tokensOut": 33,
   "tokensThinking": 356,
   "costUsd": 0.00105,
   "latencyMs": 4573,
   "firstTextMs": 4565
  },
  {
   "run": 2,
   "step": "question",
   "wallMs": 7988.5924170012,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16253,
   "tokensOut": 106,
   "tokensThinking": 425,
   "costUsd": 0.006203,
   "latencyMs": 7940,
   "firstTextMs": 7938
  },
  {
   "run": 2,
   "step": "after approval",
   "wallMs": 2461.772624999867,
   "approveMs": 52.62129200127674,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 240,
   "tokensOut": 34,
   "tokensThinking": 0,
   "costUsd": 0.000157,
   "latencyMs": 2443,
   "firstTextMs": 2440
  },
  {
   "run": 3,
   "step": "question",
   "wallMs": 5642.5575419998495,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16128,
   "tokensOut": 119,
   "tokensThinking": 358,
   "costUsd": 0.006031,
   "latencyMs": 5613,
   "firstTextMs": 5612
  },
  {
   "run": 3,
   "step": "after approval",
   "wallMs": 2086.5909999993164,
   "approveMs": 56.91091600237996,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 253,
   "tokensOut": 41,
   "tokensThinking": 0,
   "costUsd": 0.000178,
   "latencyMs": 2063,
   "firstTextMs": 2058
  },
  {
   "run": 4,
   "step": "question",
   "wallMs": 6763.312208997377,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16461,
   "tokensOut": 129,
   "tokensThinking": 587,
   "costUsd": 0.006728,
   "latencyMs": 6730,
   "firstTextMs": 6729
  },
  {
   "run": 4,
   "step": "after approval",
   "wallMs": 3043.5581669989915,
   "approveMs": 60.542582999914885,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 263,
   "tokensOut": 42,
   "tokensThinking": 357,
   "costUsd": 0.001076,
   "latencyMs": 3005,
   "firstTextMs": 3002
  },
  {
   "run": 6,
   "step": "question",
   "wallMs": 6931.212667001091,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16283,
   "tokensOut": 115,
   "tokensThinking": 417,
   "costUsd": 0.006215,
   "latencyMs": 6866,
   "firstTextMs": 6863
  },
  {
   "run": 6,
   "step": "after approval",
   "wallMs": 3229.674750000413,
   "approveMs": 118.4653749987774,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 249,
   "tokensOut": 35,
   "tokensThinking": 338,
   "costUsd": 0.001007,
   "latencyMs": 3201,
   "firstTextMs": 3200
  },
  {
   "run": 7,
   "step": "question",
   "wallMs": 6119.296041997586,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16344,
   "tokensOut": 129,
   "tokensThinking": 494,
   "costUsd": 0.006461,
   "latencyMs": 5989,
   "firstTextMs": 5983
  },
  {
   "run": 7,
   "step": "after approval",
   "wallMs": 2561.172499998065,
   "approveMs": 101.62554199996521,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 263,
   "tokensOut": 38,
   "tokensThinking": 0,
   "costUsd": 0.000174,
   "latencyMs": 2530,
   "firstTextMs": 2525
  },
  {
   "run": 8,
   "step": "question",
   "wallMs": 7926.778958997602,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16180,
   "tokensOut": 125,
   "tokensThinking": 354,
   "costUsd": 0.006051,
   "latencyMs": 7868,
   "firstTextMs": 7861
  },
  {
   "run": 8,
   "step": "after approval",
   "wallMs": 2732.1521250014484,
   "approveMs": 164.47108400097932,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 259,
   "tokensOut": 38,
   "tokensThinking": 0,
   "costUsd": 0.000173,
   "latencyMs": 2688,
   "firstTextMs": 2687
  },
  {
   "run": 9,
   "step": "question",
   "wallMs": 6250.379167002393,
   "modelCalls": 3,
   "toolCalls": 2,
   "tokensIn": 16225,
   "tokensOut": 112,
   "tokensThinking": 377,
   "costUsd": 0.00609,
   "latencyMs": 6122,
   "firstTextMs": 6120
  },
  {
   "run": 9,
   "step": "after approval",
   "wallMs": 3766.6031249973457,
   "approveMs": 138.20695799950045,
   "modelCalls": 1,
   "toolCalls": 0,
   "tokensIn": 246,
   "tokensOut": 39,
   "tokensThinking": 378,
   "costUsd": 0.001116,
   "latencyMs": 3723,
   "firstTextMs": 3718
  }
 ],
 "failures": [
  {
   "run": 5,
   "step": "question",
   "status": 200,
   "last": {
    "type": "done",
    "turnId": "turn_41e89702-a4f0-4e99-bb99-26067b291bc2",
    "metrics": {
     "modelCalls": 2,
     "toolCalls": 1,
     "tokensIn": 10623,
     "tokensOut": 86,
     "tokensThinking": 415,
     "costUsd": 0.004439,
     "latencyMs": 5197,
     "firstTextMs": 5193
    }
   }
  }
 ]
}
```
