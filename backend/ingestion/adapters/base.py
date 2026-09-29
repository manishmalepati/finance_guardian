from abc import ABC, abstractmethod

from backend.domain.transactions import ParsedTransaction


class StatementAdapter(ABC):
    source: str

    @abstractmethod
    def parse(self, content: bytes) -> list[ParsedTransaction]:
        raise NotImplementedError
