### Phase 1: GPU Foundation & Tensor Infrastructure

- [ ] Set up cargo workspace with `zipy-core` and `zipy-runtime`
- [ ] Initialize `wgpu` instance with adapter selection (Discrete > Integrated)
- [ ] Implement `.safetensors` parser to map model headers to metadata
- [ ] Create a staging belt for efficient `CPU -> GPU` weight transfers
- [ ] Implement a basic `Tensor` abstraction for GPU-resident buffers
- [ ] Write a validation suite to compare GPU matmul results against a CPU reference (ndarray)
- [ ] Set up CI pipeline for WGSL shader compilation checks

---

### Phase 2: Transformer Compute Kernels (The Math)

- [ ] Implement optimized MatMul shader (Linear layers)
- [ ] Implement RMSNorm and LayerNorm shaders
- [ ] Implement RoPE (Rotary Positional Embeddings) kernel
- [ ] Implement Activation kernels (SiLU / SwiGLU)
- [ ] Implement Softmax kernel for attention scores
- [ ] Add mixed-precision support (FP16 / BF16) to all kernels

---

### Phase 3: The Inference Engine (The Generation Loop)

- [ ] Implement the full Transformer block dispatch logic
- [ ] Create the token-to-id / id-to-token wrapper (Tokenizer integration)
- [ ] Implement the generation loop (Argmax, Top-K, Top-P sampling)
- [ ] Implement Logits processors (Temperature, Repetition penalty)
- [ ] Add stop-token detection and sequence handling

---

### Phase 4: Systems Engineering & PagedAttention

- [ ] Implement a VRAM block allocator (The PagedAttention foundation)
- [ ] Create the Block Table manager to map logical sequences to physical GPU blocks
- [ ] Implement the PagedAttention kernel (Multi-head attention using block tables)
- [ ] Implement KV cache eviction policies
- [ ] Add support for "spilling" KV blocks to host RAM or NVMe SSD

---

### Phase 5: Edge Deployment & Sensor Fusion

- [ ] Define the quantization pipeline (INT8 / INT4 weight quantization for edge targets)
- [ ] Implement model distillation utilities to reduce model size for constrained environments
- [ ] Add multi-modal input support (camera frames, IMU data alongside text tokens)
- [ ] Create a unified VRAM pool manager to balance sensor buffers and inference cache
- [ ] Implement a low-latency scheduler optimized for real-time autonomous decision loops
- [ ] Add speculative decoding to reduce time-to-first-token on edge hardware

---

### Phase 6: Scheduling & Optimization

- [ ] Implement Continuous Batching (iteration-level scheduling)
- [ ] Add async polling mechanism to maximize GPU utilization
- [ ] Implement headless support for running Zipy as a background service
- [ ] Benchmark end-to-end RAG latency (Time-to-First-Token)
- [ ] Create `cargo bench` suite for hardware-specific profiling (NVIDIA vs Apple Silicon)
