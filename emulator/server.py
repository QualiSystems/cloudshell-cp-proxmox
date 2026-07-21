#!/usr/bin/env python
"""Convenience launcher so the emulator can be started as `python emulator/server.py`
in addition to `python -m proxmox_emulator` from inside the emulator/ directory.
"""
from proxmox_emulator.cli import main

if __name__ == "__main__":
    main()
