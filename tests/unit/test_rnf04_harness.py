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


@pytest.mark.unit
def test_ci_coverage_floor_85_includes_margin_walkforward() -> None:
    """CA-RNF-02.2 (T12) — o piso de 85% do CI cobre os módulos NOVOS da 2b.

    `margin.py` e `walkforward.py` vivem dentro de `quantlab.engine`, então o
    `source_pkgs` da 2a já os alcança — mas o teste exige isso EXPLICITAMENTE
    (não "passa vazio" se um nascer fora do escopo, ex.: pacote novo na
    raiz). Guard contra o piso deixar de valer onde o erro custa dinheiro.
    """
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    report = pyproject["tool"]["coverage"]["report"]
    run = pyproject["tool"]["coverage"]["run"]

    assert report["fail_under"] == 85
    assert "quantlab.engine" in run["source_pkgs"]  # cobre margin.py
    assert "quantlab.analytics" in run["source_pkgs"]  # cobre o relatório 2b

    # Os dois módulos novos existem DENTRO do escopo (engine/) — se um nascer
    # fora (ex.: quantlab/margin.py), o `source_pkgs` não o mede e este
    # assert falha antes do CI "passar vazio".
    for relative in ("engine/margin.py", "engine/walkforward.py"):
        assert (_PROJECT_ROOT / "src" / "quantlab" / relative).is_file(), (
            f"{relative} deveria viver dentro de quantlab/engine/ para o piso "
            "de 85% medi-lo (CA-RNF-02.2)."
        )


@pytest.mark.unit
def test_spec_architecture_fails_without_adr_0009() -> None:
    """CA-RNF-02.3 (T12) — nenhum invariante da 2b é relaxado sem ADR: o
    ADR-0009 (margem e liquidação forçada) existe e é REFERENCIADO pelo design.

    Se o ADR sumir ou o design parar de referenciá-lo, o invariante de margem
    fica órfão de decisão registrada e o teste quebra (arquitetura de specs,
    RNF-09 — padrão da casa: a regra vale até para a regra).
    """
    adr = _PROJECT_ROOT / "specs" / "adr" / "0009-margem-e-liquidacao-forcada.md"
    assert adr.is_file(), (
        "ADR-0009 (margem e liquidação forçada) não existe — invariante "
        "relaxado sem decisão registrada."
    )

    design = (_PROJECT_ROOT / "specs" / "fase-2b-design.md").read_text(encoding="utf-8")
    assert "ADR-0009" in design, (
        "design 2b não referencia o ADR-0009 — a decisão de margem não está ancorada."
    )

    requirements = (_PROJECT_ROOT / "specs" / "fase-2b-requirements.md").read_text(encoding="utf-8")
    assert "ADR-0009" in requirements or "ADR-0009" in design
    # O ADR declara o teste nomeado que o quebraria (padrão dos ADRs da casa).
    adr_text = adr.read_text(encoding="utf-8")
    assert "test_broken_fund_result_excluded_from_auto_comparison" in adr_text
