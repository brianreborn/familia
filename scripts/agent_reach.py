#!/usr/bin/env python3
"""CLI shim: Agent-Reach wiring (implementation in familia_agent_reach.py).

Named separately from the upstream `agent_reach` package in the pin checkout
so `import agent_reach` inside a hermes child with the pin on PYTHONPATH still
resolves to Panniantong/Agent-Reach.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import familia_agent_reach as m
sys.exit(m.main() or 0)
