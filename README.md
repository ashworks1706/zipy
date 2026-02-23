<p align="center">
  <img width="1873" height="291" alt="image" src="https://github.com/user-attachments/assets/70e9e233-3e7d-40b8-b7e0-3d8e9cc1dc83" />
</p>

<p align="center">
    <b>GPU Compute Runtime for Retrieval Augmented Systems</b>
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

 

Zipy is a Rust-based GPU runtime designed to accelerate retrieval-augmented generation (RAG) workflows. It co-locates embedding retrieval and LLM inference on the same GPU, orchestrates memory across retriever and generator components, and minimizes host-device transfers to improve end-to-end latency in RAG systems.

- On-GPU embedding cache for retrieval workloads
- GPU-resident KV cache management for LLM inference
- Retrieval-to-attention memory fusion
- Batched vector search and generation scheduling
- RAG-aware VRAM pooling and memory planning
- Mixed-precision support (FP16 / BF16)
- RAG-aware fine-tuning acceleration (hard negative mining & in-loop retrieval)
- CLI benchmarking for RAG latency, throughput, and GPU utilization
- Standalone library or use with [Piramid](https://piramiddb.com/)

## Quick Start

TBD.

## Contributing

TBD.

## License

[Apache 2.0 License](LICENSE)

## Acknowledgments

Built by @ashworks1706 as the compute layer for Piramid.

 
