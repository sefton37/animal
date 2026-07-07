# Workstream 3b — Model roster (researched 2026-07-07, verified vs live HF configs)

Roster seats filled by **training lineage** (not brand). All KV math computed from
live `config.json` values. Target: llama.cpp GGUF on RTX 4070 Ti SUPER (16 GB) /
251 GB DDR4 (measured **47 GB/s**, workstream 1) / 48 threads.

**Lineage diversity check:** Coder/Architect = Qwen (Alibaba); Judge = gpt-oss
(OpenAI); Auditor = Mistral; Jury = Qwen / Google / Meta. Coder, judge, auditor
are three distinct lineages. **Phi is deliberately excluded** — Phi-4 is
GPT-4o-distilled, so it is NOT independent from the gpt-oss judge (would collapse
two "independent" votes into one OpenAI ancestor).

## Roster

| Seat | Model | Lineage | Quant | Disk GB | KV 8k/32k (q8) | MoE offload | Tool-calling |
|------|-------|---------|-------|--------:|----------------|-------------|--------------|
| Coder | Qwen3-Coder-30B-A3B-Instruct | Qwen | Q5_K_M (Q4 lean) | 21.7 (18.6) | 0.375 / 1.5 GiB | Yes `--n-cpu-moe`, ~20–24 GB RAM | Strong (76.6% BFCL-v2) |
| Architect | Qwen3-30B-A3B-Thinking-2507 | Qwen | Q4_K_M | ~18.6 | 0.375 / 1.5 GiB | Yes, ~18–20 GB RAM | Good; long CoT |
| Judge | gpt-oss-20b | OpenAI | MXFP4 native | 14.0 | 0.19 / 0.75 GiB | No (fits alone) | Harmony tool-training (BFCL DIRECTIONAL) |
| Auditor | Mistral-Small-3.2-24B-2506 | Mistral | Q4_K_M | 14.3 | 0.625 / 2.5 GiB | No; cap ≤16k ctx | Native tool format |
| Jury-1 | Qwen3-4B-Instruct-2507 | Qwen | Q4_K_M | ~2.5 | CPU (`num_gpu=0`) | — | Good for size |
| Jury-2 | Gemma-3-4B-it | Google | Q4_K_M | ~2.9 | CPU | — | Fair |
| Jury-3 | Llama-3.2-3B-Instruct | Meta | Q4_K_M | ~2.0 | CPU | — | Fair |
| Embedder | Qwen3-Embedding-0.6B | Qwen | Q8_0 | 0.64 | negligible | No | top code retrieval @size |

**Bake-off alternate:** Devstral-Small-2-24B-Instruct-2512 (Mistral, dense 24B,
agent-first, tops small-model SWE-bench) Q4_K_M 14.3 GB — worth a Phase-0
head-to-head for the coder/auditor seat. Dense 24B crowds out the embedder in
Config A (would need embedder on CPU or a ~14B dense coder like Qwen2.5-Coder-14B).

## VRAM fit (usable ≈ 15.5 GB)

- **Config A (build phase):** Coder as MoE (`--n-cpu-moe`, experts→RAM) → GPU
  holds attention+router+embeddings+KV ≈ 2–3 GB weights + 1.5 GB KV@32k + 3.5 GB
  router/embedder ≈ **7–8 GB. Closes with room** → tune `--n-cpu-moe` to pull hot
  expert layers back onto GPU up to ~14 GB for throughput.
- **Config B (judge phase):** gpt-oss-20b 14.0 + KV@8k f16 0.375 = **14.4 GB ✅**;
  Mistral-24B auditor 14.3 + KV@8k q8 0.625 = **14.9 GB ✅** (cap ≤16k; Q4 not Q5).

## Download tally

- **Must-have to start benchmarking ≈ 73.5 GB:** Coder 18.6 + Architect 18.6 +
  gpt-oss 14.0 + Mistral 14.3 + Embedder 0.64 + jury (2.5 + 2.9 + 2.0).
- **Nice-to-have ≈ 20 GB:** Devstral 14.3 (bake-off) + Qwen3-Embedding-4B 2.5 +
  Coder Q5 delta +3.1.
- **Premium/DIRECTIONAL:** GLM-4.5-Air (Zhipu, 106B-A12B, tops BFCL-v3 ~76–78%,
  a 4th lineage) ≈ 70 GB — size/throughput unverified on-box.

## DIRECTIONAL flags

gpt-oss BFCL-v3 number unverified (asserted from Harmony tool-training); GLM-4.5-Air
size/throughput unverified; Qwen3-Thinking Q4 size inferred from sibling; jury Q4
sizes approximate; Config-A GPU-resident non-expert weight (~2–3 GB) is a
param-count estimate — confirm from llama.cpp load logs on first run.

Sources: HF repos + ollama.com per model (see git history / research digest); BFCL
gorilla.cs.berkeley.edu leaderboard.
