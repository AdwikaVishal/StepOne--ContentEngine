"""
MLX Inference Configuration
Loads settings from environment variables with sensible defaults.
Used by both the MLX client and worker.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MLXConfig:
    """MLX inference configuration loaded from environment."""

    # Model selection
    model_id: str
    model_path: str | None
    model_bits: int

    # Generation limits
    max_tokens: int
    max_context: int
    temperature: float

    # Timeouts
    timeout_seconds: int

    # Worker
    worker_python: str
    worker_script: str

    # Memory guard thresholds
    min_available_gb: float
    max_swap_percent: float
    max_memory_percent: float

    @staticmethod
    def from_env() -> "MLXConfig":
        """Load configuration from environment variables."""
        return MLXConfig(
            model_id=os.getenv("MLX_MODEL_ID", "mlx-community/Qwen2.5-0.5B-Instruct-4bit"),
            model_path=os.getenv("MLX_MODEL_PATH") or None,
            model_bits=int(os.getenv("MLX_MODEL_BITS", "4")),
            max_tokens=int(os.getenv("MLX_MAX_TOKENS", "256")),
            max_context=int(os.getenv("MLX_MAX_CONTEXT", "2048")),
            temperature=float(os.getenv("MLX_TEMPERATURE", "0.0")),
            timeout_seconds=int(os.getenv("MLX_TIMEOUT_SECONDS", "60")),
            worker_python=os.getenv("MLX_WORKER_PYTHON", ".venv-mlx/bin/python"),
            worker_script=os.getenv("MLX_WORKER_SCRIPT", "scripts/mlx_worker.py"),
            min_available_gb=float(os.getenv("MLX_MIN_AVAILABLE_GB", "2.0")),
            max_swap_percent=float(os.getenv("MLX_MAX_SWAP_PERCENT", "50.0")),
            max_memory_percent=float(os.getenv("MLX_MAX_MEMORY_PERCENT", "85.0")),
        )

    def resolve_model_path(self) -> str:
        """Resolve the model path - local path takes precedence over HF repo."""
        if self.model_path and Path(self.model_path).exists():
            return self.model_path
        return self.model_id

    def validate(self) -> list[str]:
        """Validate configuration, return list of warnings/errors."""
        issues = []

        if self.max_tokens > 1024:
            issues.append(f"MLX_MAX_TOKENS={self.max_tokens} is high for 8GB RAM; consider <=512")

        if self.max_context > 4096:
            issues.append(f"MLX_MAX_CONTEXT={self.max_context} is high; consider <=4096")

        if self.temperature < 0 or self.temperature > 2:
            issues.append(f"MLX_TEMPERATURE={self.temperature} should be 0.0-2.0")

        if self.timeout_seconds < 10 or self.timeout_seconds > 300:
            issues.append(f"MLX_TIMEOUT_SECONDS={self.timeout_seconds} should be 10-300")

        if self.min_available_gb < 0.5 or self.min_available_gb > 8:
            issues.append(f"MLX_MIN_AVAILABLE_GB={self.min_available_gb} should be 0.5-8.0")

        if self.max_swap_percent < 0 or self.max_swap_percent > 100:
            issues.append(f"MLX_MAX_SWAP_PERCENT={self.max_swap_percent} should be 0-100")

        if self.max_memory_percent < 0 or self.max_memory_percent > 100:
            issues.append(f"MLX_MAX_MEMORY_PERCENT={self.max_memory_percent} should be 0-100")

        worker_path = Path(self.worker_python)
        if not worker_path.exists():
            issues.append(f"MLX worker python not found: {worker_path}")

        script_path = Path(self.worker_script)
        if not script_path.exists():
            issues.append(f"MLX worker script not found: {script_path}")

        return issues


# Global config instance (loaded once)
_config: MLXConfig | None = None


def get_config() -> MLXConfig:
    """Get the global MLX configuration."""
    global _config
    if _config is None:
        _config = MLXConfig.from_env()
    return _config


def reload_config() -> MLXConfig:
    """Reload configuration from environment."""
    global _config
    _config = MLXConfig.from_env()
    return _config