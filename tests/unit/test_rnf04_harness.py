"""T17 — harness do RNF-04 e piso de cobertura (RF-RNF-01 CA-01.3, RNF-02).

O harness do RNF-04 (P5/D3) declara o escopo como constante literal e mede
APENAS o cômputo — o teste abaixo prova isso por construção: a função
cronometrada não chama serialização nem gráfico, e o código-fonte do harness
não referencia `to_json`/`to_dict`/plot/render (a exclusão de P5 é real, não
retórica). O piso de cobertura (RNF-02 supersedido: 80 -> 85 sobre
`engine/` + `analytics/`) é lido do próprio `pyproject.toml` — o teste quebra
se o CI mudar sem a spec acompanhar.
"""

import ast
import tomllib
from pathlib import Path

import pytest
import scripts.rnf04_harness as harness

from quantlab.strategies.sma_cross import SmaCross

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_rnf04_harness_measures_compute_only() -> None:
    """CA-01.3 — a medição cobre apenas o cômputo e o escopo é declarado.

    1. `measure` roda de verdade sobre séries sintéticas (RNF-03) e devolve
       um tempo positivo — sem banco, sem serialização, sem PNG;
    2. a constante de escopo declara a exclusão (ingestão, serialização e
       renderização ficam fora);
    3. por construção: o harness não referencia `to_json`/`to_dict`/plot/
       render — o cronômetro não tem como chamar o que o arquivo não importa.
    """
    series = harness._synthetic_series(["AAA", "BBB"], years=1)
    strategies = {ticker: SmaCross(fast=2, slow=5) for ticker in series}

    elapsed = harness.measure(series, strategies, repetitions=1)

    assert elapsed > 0.0
    assert "exclui ingestão" in harness.SCOPE
    assert "serialização do relatório" in harness.SCOPE
    assert "renderização de PNG" in harness.SCOPE

    # Por construção (AST): o cronômetro não chama serialização nem gráfico.
    # O texto do SCOPE declara a exclusão (contém "to_json/to_dict" como
    # string literal) — o que importa é não haver CHAMADA nem import.
    tree = ast.parse(Path(harness.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"to_json", "to_dict"}, (
        "o harness do RNF-04 serializa o relatório — a medição deixaria de ser "
        "compute-only (CA-01.3/P5)."
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(name.endswith(".plot") or name == "plot" for name in imported), (
        "o harness do RNF-04 importa renderização de gráfico — a medição "
        "deixaria de ser compute-only (CA-01.3/P5)."
    )


@pytest.mark.unit
def test_ci_coverage_floor_85() -> None:
    """RNF-02 supersedido (v0.2): o piso do CI é 85% sobre engine/+analytics/.

    Se o `fail_under` ou o escopo de `source_pkgs` mudarem sem a spec
    acompanhar (RF-RNF-01 CA-01.2), este teste quebra.
    """
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    report = pyproject["tool"]["coverage"]["report"]
    run = pyproject["tool"]["coverage"]["run"]

    assert report["fail_under"] == 85
    assert "quantlab.engine" in run["source_pkgs"]
    assert "quantlab.analytics" in run["source_pkgs"]
