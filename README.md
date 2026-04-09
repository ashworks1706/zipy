<p align="center">
  <img width="1873" height="291" alt="image" src="https://github.com/user-attachments/assets/70e9e233-3e7d-40b8-b7e0-3d8e9cc1dc83" />
</p>

<p align="center">
    <b>Reliable Inference Runtime for Autonomous Systems</b>
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

---

**Zipy** is a constraint-aware LLM inference runtime built in Rust and wgpu for low-latency decision-making in autonomous systems. It is designed to run directly on-device under strict memory, compute, and power constraints such as rovers, drones, and edge-based agents by enforcing bounded execution, fallback modes, and structured outputs.


- Native `safetensors` loading with efficient GPU buffer management via `wgpu`
- Custom WGSL kernels for Transformer operations (MatMul, RoPE, RMSNorm)
- Quantized inference for reduced memory footprint on edge devices
- PagedAttention for efficient KV-cache management under fragmented VRAM
- Low-latency inference optimized for real-time decision loops
- Multi-modal input support (camera frames, IMU data, sensor streams)
- Persistent KV-cache offloading to NVMe to reduce recomputation overhead
- Continuous batching for fine-grained request scheduling
- Model distillation support for deployment in constrained environments
- FP16 / BF16 precision support

---

## Quick Start

TBD.

## Usage

TBD.

## Contributing

TBD.

## License

[Apache 2.0 License](LICENSE)

## Acknowledgments

Built by @ashworks1706 for real-time autonomous systems operating under constrained environments.
