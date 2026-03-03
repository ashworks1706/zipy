<p align="center">
  <img width="1873" height="291" alt="image" src="https://github.com/user-attachments/assets/70e9e233-3e7d-40b8-b7e0-3d8e9cc1dc83" />
</p>

<p align="center">
    <b>GPU Inference Engine for Retrieval Augmented Systems</b>
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

 

Zipy is an LLM inference engine implemented in Rust and wgpu. It is designed to operate as the compute layer for Piramid, focusing on reducing the "prefill" bottleneck in RAG by fusing vector retrieval with the LLM's attention mechanism. The project moves beyond standard text-based RAG pipelines by allowing the vector database to communicate directly with the inference engine's memory space, enabling zero-copy context injection through shared KV-cache management.

- Native safetensors weight loading and GPU buffer management via wgpu
- Custom WGSL kernels for Transformer operations (MatMul, RoPE, RMSNorm)
- PagedAttention for fragmented KV-cache management in VRAM
- Shared memory protocol for direct pointer-passing between Piramid and Zipy
- Persistent KV-cache offloading to NVMe SSDs to bypass LLM re-computation
- Continuous batching for iteration-level request scheduling
- Support for FP16 and BF16 precision

## Quick Start

TBD.

## Contributing

TBD.

## License

[Apache 2.0 License](LICENSE)

## Acknowledgments

Built by @ashworks1706 as the compute layer for Piramid.

 
