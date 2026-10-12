"""FR-10, NFR-05: fake Graph HTTP boundary first; native networking is HUMAN-invoked."""

from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, JsonValue

from instabay.adapters.graph_models import GraphTransportError
from instabay.core.schemas import Boundary


class GraphResponse(Boundary):
    """FR-10: status, structured JSON and a safe optional backoff hint."""

    status_code: int = Field(ge=100, le=599)
    body: dict[str, JsonValue]
    retry_after_s: float | None = Field(default=None, ge=0)


class GraphTransport(Protocol):
    """NFR-05: access-token ownership stays inside the native adapter, outside fixtures."""

    def request(
        self, method: Literal["GET", "POST"], path: str, params: dict[str, str]
    ) -> GraphResponse: ...


class Exchange(Boundary):
    """NFR-07: explicit offline contract, not a cassette claimed to come from a live token."""

    method: Literal["GET", "POST"]
    path: str
    params: dict[str, str]
    response: GraphResponse | None = None
    failure: Literal["timeout"] | None = None


class Contract(Boundary):
    """NFR-07: ordered request/response sequence for one synthetic scenario."""

    provenance: Literal["synthetic_contract_fixture"] = "synthetic_contract_fixture"
    exchanges: list[Exchange]


class FixtureGraphTransport:
    """NFR-07: unknown, out-of-order and extra requests fail; zero sockets or keys."""

    def __init__(self, path: Path) -> None:
        self.contract = Contract.model_validate_json(path.read_bytes())
        self.calls: list[tuple[str, str, dict[str, str]]] = []

    def request(
        self, method: Literal["GET", "POST"], path: str, params: dict[str, str]
    ) -> GraphResponse:
        index = len(self.calls)
        if index >= len(self.contract.exchanges):
            raise AssertionError("Unexpected extra Graph request")
        expected = self.contract.exchanges[index]
        if (method, path, params) != (expected.method, expected.path, expected.params):
            raise AssertionError(f"Graph request did not match fixture exchange {index}")
        self.calls.append((method, path, params.copy()))
        if expected.failure:
            raise GraphTransportError("Synthetic Graph timeout; outcome may be unknown")
        if expected.response is None:
            raise AssertionError("Contract exchange lacks a response")
        return expected.response

    def assert_consumed(self) -> None:
        assert len(self.calls) == len(self.contract.exchanges), "Contract has unused exchanges"
