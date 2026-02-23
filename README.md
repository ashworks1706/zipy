<p align="center">
  <img width="1873" height="291" alt="image" src="https://github.com/user-attachments/assets/70e9e233-3e7d-40b8-b7e0-3d8e9cc1dc83" />
</p>

<p align="center">
    <b>GPU Compute Runtime for ML Inference & Retrieval</b>
</p>

<p align="center">
    <a href="https://crates.io/crates/zipy"><img src="https://img.shields.io/crates/v/zipy.svg" alt="crates.io"></a>
    <a href="https://www.npmjs.com/package/zipy-compute"><img src="https://img.shields.io/npm/v/zipy-compute.svg" alt="npm"></a>
    <a href="https://pypi.org/project/zipy-compute/"><img src="https://img.shields.io/pypi/v/zipy-compute.svg" alt="PyPI"></a>
</p>

<p align="center">
    <a href="#quick-start">Quick Start</a> •
    <a href="#usage">Usage</a> •
    <a href="#contributing">Contributing</a>
</p>

 

Zipy is a Rust-based compute runtime built to accelerate embedding-heavy ML systems. It manages GPU memory, schedules vector workloads across CPU/GPU, and eliminates unnecessary host-device roundtrips for retrieval and inference pipelines.

- On-GPU embedding cache (LRU / frequency-based)
- Batched vector operations (dot-product, cosine similarity, top-k search)
- Automatic CPU/GPU workload scheduling
- Zero-copy host ↔ device transfers (pinned memory / DMA)
- VRAM memory pooling and eviction policies
- Mixed-precision compute support (FP16/BF16)
- CLI benchmarking for latency, throughput, and GPU utilization
- Optional KV cache layer for LLM inference acceleration
- Standalone library or use with [Piramid](https://piramiddb.com/)

## Quick Start

TBD.

## Contributing

TBD.

## License

[Apache 2.0 License](LICENSE)

## Acknowledgments

Built by @ashworks1706 as the compute layer for Piramid.

 
