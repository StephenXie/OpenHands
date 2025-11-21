vllm serve Qwen/Qwen3-8B --gpu-memory-utilization 0.95 --tensor-parallel-size 1 --port 8000 --enable-auto-tool-choice --tool-call-parser hermes
