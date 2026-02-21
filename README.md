<p align="center">
  <img width="1873" height="291" alt="image" src="https://github.com/user-attachments/assets/70e9e233-3e7d-40b8-b7e0-3d8e9cc1dc83" />
</p>

<p align="center">
    <b>Compute Kernel Runtime for Vector Operations</b>
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

 

Zipy is a compute kernel runtime built in Rust that manages CPU, RAM, GPU, and VRAM resources for vector database operations specifically on edge devices or cheap hardware. It decides where each operation runs and handles data movement automatically.

- Manages CPU threads, RAM allocation, GPU memory, VRAM pooling
- Automatic CPU vs GPU scheduling
- Zero-copy transfers with DMA
- Works on NVIDIA, AMD, Intel, Apple GPUs
- Standalone library or use with [Piramid](https://piramiddb.com/)

## Quick Start

TBD.

## Contributing

TBD.

## License

[Apache 2.0 License](LICENSE)

## Acknowledgments

Built by @ashworks1706 as the compute layer for Piramid.

 
