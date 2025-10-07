# SQUINT: Multi-Domain Quantum Compiler

> **S**emantic **Q**uantum **INT**erpreter: A compiler that understands thermodynamics, topology, and semantic structure

![MIT](https://img.shields.io/badge/License-MIT-green.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Status](https://img.shields.io/badge/status-v0.1.0-brightgreen)

SQUINT represents a paradigm shift from traditional quantum compilation to **physical domain compilation**, enabling programmers to express algorithms in the natural language of their physical implementation while automatically handling cross-domain constraints.

## 🌟 Features

- **Multi-Domain Awareness**: Simultaneous optimization across semantic, topological, and thermodynamic domains
- **Automatic Constraint Satisfaction**: Intelligent insertion of timing, coherence, and connectivity constraints
- **Quantum Control Generation**: Output to QUA, OpenPulse, and other quantum control languages
- **Extensible Kernel System**: Support for Floquet dynamics, topological computation, and custom physical models
- **Physical Intuition Preservation**: Maintains semantic meaning through compilation pipeline

## 🚀 Quick Start

```python
from squint import SquintCompiler
from squint.kernels import FloquetKernel

# Compile from SQUINT language
compiler = SquintCompiler()
result = compiler.compile("examples/basic/calibrated_epr.squint")
print(result.qua_code)

# Or use programmatic kernel API
floquet_kernel = FloquetKernel(
    period_τ=100,
    modulation_function=lambda phase: math.sin(phase)
)
operations = floquet_kernel.evolve_cycle(n_cycles=50)
