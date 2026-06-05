# StudioFlow Core Engine

This folder contains the StudioFlow core engine prototype (Python). It is a self-contained audio engine module intended to be embedded within a mobile or desktop UI via FFI/IPC.

Files:
- studioflow_core.py — the main engine module (DSP, project model, export, drivers)

Quickstart
---------

Prerequisites:
- Python 3.9+
- numpy
- (optional) soundfile, scipy, sounddevice, requests for full features

Run example usage (will synthesize test tones and attempt exports):

python engine/studioflow_core.py

Notes
-----
- If sounddevice or soundfile are not installed, the engine will still run but real-time output and WAV export will be disabled.
- The module is intended as a backend engine; integrate into your site by offering the file for download or by running a small server that exposes the example run logs.
