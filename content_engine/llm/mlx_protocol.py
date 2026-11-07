"""
MLX Worker Protocol
JSON-lines request/response serialization for subprocess communication.
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, Literal


# Error codes
class ErrorCode:
    INVALID_REQUEST = "INVALID_REQUEST"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    GENERATION_FAILED = "GENERATION_FAILED"
    MEMORY_GUARD_REJECTED = "MEMORY_GUARD_REJECTED"
    TIMEOUT = "TIMEOUT"
    WORKER_SHUTTING_DOWN = "WORKER_SHUTTING_DOWN"
    UNKNOWN_REQUEST = "UNKNOWN_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"


@dataclass(frozen=True)
class GenerationRequest:
    """Request sent to MLX worker."""
    id: str
    system: str
    user: str
    max_tokens: int
    temperature: float
    timeout: int
    model: str = ""
    timestamp: float = field(default_factory=time.time)

    @staticmethod
    def create(
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
        timeout: int,
        model: str = "",
    ) -> "GenerationRequest":
        if not system and not user:
            raise ValueError("At least one of system or user prompt must be non-empty")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if temperature < 0 or temperature > 2:
            raise ValueError("temperature must be between 0.0 and 2.0")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        return GenerationRequest(
            id=str(uuid.uuid4())[:8],
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            model=model,
        )

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


@dataclass(frozen=True)
class GenerationResponse:
    """Response received from MLX worker."""
    id: str
    text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: int = 0
    model: str = ""
    error: Optional[str] = None
    error_code: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def success(self) -> bool:
        return self.error is None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json_line(line: str) -> "GenerationResponse":
        data = json.loads(line)
        return GenerationResponse(**data)


@dataclass(frozen=True)
class HealthCheckRequest:
    """Health check request."""
    id: str
    type: Literal["health"] = "health"
    timestamp: float = field(default_factory=time.time)

    @staticmethod
    def create() -> "HealthCheckRequest":
        return HealthCheckRequest(id=str(uuid.uuid4())[:8])

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


@dataclass(frozen=True)
class HealthCheckResponse:
    """Health check response."""
    id: str
    status: Literal["ok", "error"]
    model_loaded: bool
    model: str = ""
    memory_pressure: float = 0.0
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json_line(line: str) -> "HealthCheckResponse":
        data = json.loads(line)
        return HealthCheckResponse(**data)


@dataclass(frozen=True)
class ShutdownRequest:
    """Shutdown request."""
    id: str
    type: Literal["shutdown"] = "shutdown"
    timestamp: float = field(default_factory=time.time)

    @staticmethod
    def create() -> "ShutdownRequest":
        return ShutdownRequest(id=str(uuid.uuid4())[:8])

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


# Request type union for type hints
Request = GenerationRequest | HealthCheckRequest | ShutdownRequest
Response = GenerationResponse | HealthCheckResponse


def parse_request(line: str) -> Request:
    """Parse a JSON line into the appropriate request type."""
    data = json.loads(line)
    req_type = data.get("type")
    if req_type == "health":
        return HealthCheckRequest(**data)
    elif req_type == "shutdown":
        return ShutdownRequest(**data)
    else:
        return GenerationRequest(**data)


def parse_response(line: str) -> Response:
    """Parse a JSON line into the appropriate response type."""
    data = json.loads(line)
    # HealthCheckResponse includes status field, GenerationResponse does not
    if "status" in data and "model_loaded" in data:
        return HealthCheckResponse.from_json_line(line)
    return GenerationResponse.from_json_line(line)