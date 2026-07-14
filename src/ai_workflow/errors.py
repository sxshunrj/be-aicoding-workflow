from dataclasses import dataclass, field


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    exit_status: int = 2
    details: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message
