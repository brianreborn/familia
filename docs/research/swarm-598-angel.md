# Unified cross-platform model selection & configuration fixes

Issue: https://github.com/brianreborn/familia/issues/598
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:15 PST
Approved-content-sha256: 30c9696d184d4b8739103001308eee6a7d316a824a2a1760fd25d197563afebc

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli qwen2.5-coder-0.5b-instruct-q4_k_m.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(e) any additional information you want to add.

a) What the issue asks, in your own words:
The issue asks for a unified cross-platform model selection and configuration fixes. The goal is to ensure that all models are correctly identified and configured across different platforms, including FreeBSD and cross?platform support.

b) A proposed approach and the files or components likely involved:
The proposed approach involves creating a unified model selection and configuration system that can handle multiple models across different platforms. The system will use a registry to store the model information, including the model name, version, and SHA. The system will also use a configuration file to store the model configuration, including the model path, model name, and SHA.

c) Risks and test ideas:
There are several risks and test ideas that need to be addressed to ensure the unified model selection and configuration system works correctly. Some of the risks include:
- Model name conflicts: If multiple models have the same name, the system will not be able to identify which one to use.
- Model version conflicts: If multiple models have the same version, the system will not be able to identify which one to use.
- Model path conflicts: If multiple models have the same path, the system will not be able to identify which one to use.
- Model SHA mismatches: If multiple models have the same SHA, the system will not be able to identify which one to use.
- Model configuration conflicts: If multiple models have the same configuration, the system will not be able to identify which one to use.
- Model path conflicts: If multiple models have the same path, the system will not be able to identify which one to use.
- Model SHA mismatches: If multiple models have the same

-- swarm/angel
