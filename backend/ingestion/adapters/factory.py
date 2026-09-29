from backend.ingestion.adapters.base import StatementAdapter
from backend.ingestion.adapters.chase_pdf import ChasePdfAdapter


class AdapterFactory:
    def for_source(self, source: str) -> StatementAdapter:
        if source == "chase_pdf":
            return ChasePdfAdapter()
        raise ValueError(f"Unsupported statement source: {source}")
