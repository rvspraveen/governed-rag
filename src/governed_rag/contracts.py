"""Optional data-contract gate using corpusgate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .corpus import Chunk
from .errors import GragError

INSTALL_HINT = 'pip install "corpusgate @ git+https://github.com/rvspraveen/corpusgate@v0.2.0"'


@dataclass
class ContractResult:
    passed: bool
    errors: list[str]
    warnings: list[str]


def run_contract(contract_path: str | Path, chunks: list[Chunk]) -> ContractResult:
    try:
        import polars as pl
        from corpusgate.contract import ContractError, load_contract
        from corpusgate.runner import run_contract as run_corpusgate
    except ImportError as e:
        raise GragError(f"--contract needs corpusgate: {INSTALL_HINT}") from e
    try:
        contract = load_contract(contract_path)
    except (ContractError, OSError) as e:
        raise GragError(f"contract: {e}") from e
    df = pl.DataFrame([c.to_row() for c in chunks])
    report = run_corpusgate(contract, df, data_label="corpus chunks")

    def fmt(o: object) -> str:
        return f"{o.check} / {o.probe}: observed {o.observed}, limit {o.limit}"  # type: ignore[attr-defined]

    return ContractResult(
        passed=report.passed,
        errors=[fmt(o) for o in report.errors],
        warnings=[fmt(o) for o in report.warnings],
    )
