### Repository & Environment

- [ ] Set up cargo workspace with `core`, `runtime`, and `rag` crates
- [ ] Configure logging facade with GPU + inference tracing
- [ ] Add structured latency tracing for retrieval and generation stages
- [ ] Set up CI pipeline validating WGSL shader compilation
- [ ] Add Rust toolchain file for reproducible builds
- [ ] Implement cargo bench suite for RAG latency and GPU benchmarks

---

### Core GPU Runtime Infrastructure

- [ ] Initialize wgpu instance with backend selector
- [ ] Implement adapter selection logic (Discrete > Integrated > CPU)
- [ ] Request device and queue with required inference features
- [ ] Implement robust device loss handling and recovery
- [ ] Create compute runtime context for LLM & retrieval orchestration
- [ ] Add polling mechanism for ensuring device progress
- [ ] Implement headless support for inference servers
- [ ] Integrate async runtime for non-blocking GPU workloads

---

### RAG-Aware Memory Management

- [ ] Create unified GPU memory manager for embeddings + KV cache
- [ ] Implement GPU-resident embedding cache (LRU / frequency-based)
- [ ] Implement VRAM pooling across retrieval + inference stages
- [ ] Add dynamic memory partitioning between retriever and generator
- [ ] Implement staging belt for efficient CPU → GPU transfers
- [ ] Implement async GPU → CPU readback (for logging / metrics)
- [ ] Add memory usage tracking and fragmentation detection
- [ ] Create ring buffer allocator for transient RAG workloads

---

### Retrieval & Search Kernels

- [ ] Implement brute force flat search (GPU)
- [ ] Implement batched matrix multiplication for multi-query retrieval
- [ ] Implement fused cosine similarity kernel
- [ ] Implement top-k reduction and bitonic sort kernels
- [ ] Optimize workgroup sizes for NVIDIA vs AMD
- [ ] Add mixed precision (f16 / bf16) variants for retrieval
- [ ] Implement GPU-based centroid computation (IVF prep)
- [ ] Implement k-means clustering shader for index training

---

### RAG Fusion Layer

- [ ] Implement retrieval-to-attention tensor fusion logic
- [ ] Create GPU pipeline for embedding → context tensor conversion
- [ ] Minimize host-device roundtrips during RAG context construction
- [ ] Implement batched retrieval + generation scheduling
- [ ] Add retrieval-aware batching logic (token-length grouping)

---

### LLM Inference Runtime

- [ ] Implement model loader (gguf / safetensors)
- [ ] Implement GPU KV cache manager
- [ ] Implement paged attention memory layout
- [ ] Create block table manager for sequence generation
- [ ] Implement KV cache eviction and session-based policies
- [ ] Implement continuous batching scheduler for inference
- [ ] Add mixed-precision inference execution support

---

### RAG-Aware Fine-Tuning Acceleration

- [ ] Implement hard negative mining on GPU
- [ ] Create in-loop retrieval API for training workflows
- [ ] Add embedding dataset residency on GPU
- [ ] Implement contrastive batch acceleration kernels
- [ ] Expose PyTorch integration hooks for retrieval-aware training

---

### Transformer Compute Kernels

- [ ] Implement optimized matmul shader for linear layers
- [ ] Implement fused RMSNorm and LayerNorm shaders
- [ ] Implement SiLU and SwiGLU activation kernels
- [ ] Implement softmax kernel for attention
- [ ] Implement multi-head attention dispatch logic

---

### Inference & Sampling

- [ ] Implement logits processor for temperature scaling
- [ ] Implement top-k and top-p sampling
- [ ] Implement repetition and frequency penalty logic
- [ ] Implement stop-token detection
- [ ] Implement speculative decoding optimization

---

### Public API

- [ ] Define clean public Rust traits for runtime interaction
- [ ] Implement builder pattern for RAG runtime configuration
- [ ] Expose inference and retrieval APIs
- [ ] Create async and blocking variants
- [ ] Expose performance counters and RAG-stage metrics
- [ ] Provide integration hooks for Piramid

---

### Testing & Validation

- [ ] Create CPU reference implementations for retrieval kernels
- [ ] Implement fuzzy comparison tests for floating-point accuracy
- [ ] Add property-based tests for CPU vs GPU equivalence
- [ ] Create stress tests for VRAM exhaustion
- [ ] Implement headless CI test runner
- [ ] Benchmark end-to-end RAG latency (retrieval + generation)
