#!/usr/bin/env bash
# familia-menu.sh – Top‑level interactive menu for the Familia project
# Provides shortcuts to the most common development / deployment actions.
# Add new entries as the project evolves.

set -euo pipefail

# Helper to print a divider
hr() { echo "--------------------------------------------------"; }

while true; do
  hr
  echo "Familia – Project Menu"
  echo "1) Add a new model (add‑model.sh)"
  echo "2) Select a model for a role (select‑model.sh)"
  echo "3) Generate per‑host graph (generate_graph.py)"
  echo "4) Validate current graph (validate_graph.py)"
  echo "5) Run start.sh (launch the router)"
  echo "6) Run benchmark (benchmark.sh)"
  echo "7) Reset Termux SSH (reset_termux_ssh.sh)"
  echo "8) Exit"
  hr
  read -rp "Choose an option [1-8]: " choice
  case "$choice" in
    1)
      echo "Running add‑model.sh…"
      ./scripts/add-model.sh
      ;;
    2)
      if [[ -x ./scripts/select-model.sh ]]; then
        echo "Running select‑model.sh…"
        ./scripts/select-model.sh
      else
        echo "select‑model.sh not found – you may need to implement it first."
      fi
      ;;
    3)
      echo "Generating per‑host graph…"
      python3 ./scripts/generate_graph.py
      ;;
    4)
      echo "Validating graph…"
      ./scripts/validate_graph.py --graph graph.yaml
      ;;
    5)
      echo "Starting Familia…"
      ./start.sh
      ;;
    6)
      if [[ -x ./scripts/benchmark.sh ]]; then
        echo "Running benchmark…"
        ./scripts/benchmark.sh
      else
        echo "benchmark.sh not found – you may need to create it."
      fi
      ;;
    7)
      if [[ -x ./scripts/reset_termux_ssh.sh ]]; then
        echo "Resetting Termux SSH…"
        ./scripts/reset_termux_ssh.sh
      else
        echo "reset_termux_ssh.sh not found – you may need to create it."
      fi
      ;;
    8)
      echo "Good‑bye!"
      exit 0
      ;;
    *)
      echo "Invalid selection – please choose 1‑8."
      ;;
  esac
  echo "Press Enter to return to the menu…"
  read -r
done
