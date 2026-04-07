<p align="center">
  <img width="1873" height="291" alt="image" src="https://github.com/user-attachments/assets/70e9e233-3e7d-40b8-b7e0-3d8e9cc1dc83" />
</p>

<p align="center">
    <b>Quantized Inference Runtime for Edge Devices</b>
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

 

Zipy is a quantized LLM inference runtime implemented in Rust and wgpu, targeting resource-constrained edge devices such as rovers, drones, and autonomous systems. It focuses on maximizing inference throughput and minimizing latency under strict memory and power budgets, enabling real-time autonomous decision-making without relying on cloud connectivity.

- Native safetensors weight loading and GPU buffer management via wgpu
- Custom WGSL kernels for Transformer operations (MatMul, RoPE, RMSNorm)
- Quantization for memory efficiency on edge devices
- PagedAttention for fragmented KV-cache management in VRAM
- Low-latency inference for real-time autonomous decisions
- Multi-modal sensor support (camera frames, IMU data, and other edge inputs)
- Persistent KV-cache offloading to NVMe SSDs to bypass LLM re-computation
- Continuous batching for iteration-level request scheduling
- Model distillation support for deployment in constrained environments
- Support for FP16 and BF16 precision

## Quick Start

TBD.

## Contributing

TBD.

## License

[Apache 2.0 License](LICENSE)

## Acknowledgments

Built by @ashworks1706 for autonomous edge systems including rovers, drones, and other resource-constrained devices.

 
