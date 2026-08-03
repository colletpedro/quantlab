"""B5 — teste de arquitetura projeto-inteiro: fronteira de instante.

Generaliza o recorte que existia só para `storage/` (A3, quando o Bloco A
era o único código escrito) para **todo** o pacote `quantlab`. Design v0.3
§3.6 dá a formulação: a classe `datetime` e o aparato de fuso (`timezone`,
`tzinfo`, `UTC`) só podem aparecer em `ingestion/normalizer.py` e
`storage/repository.py` — os dois pontos de conversão declarados pela
tabela de §3.6. `date` e `timedelta` são livres em qualquer módulo: são o
vocabulário de data-calendário que RNF-07 exige em todo o domínio, e a v0.2
original proibia justamente esse vocabulário ao proibir o módulo `datetime`
inteiro (ambiguidade registrada no HANDOFF do Bloco A e corrigida na v0.3).

**Bloqueante no CI** (decisão Q3 do design, confirmada na v0.2): um aviso
não-bloqueante vira ruído e para de ser lido. Este teste falha o build.
"""

import ast
from pathlib import Path

import pytest

import quantlab

#: Os dois módulos autorizados a manipular instante e fuso — design v0.3 §3.6.
#: Caminho relativo à raiz do pacote (`src/quantlab/`), sempre com `/`.
_ALLOWED_INSTANT_MODULES = frozenset(
    {
        "ingestion/normalizer.py",
        "storage/repository.py",
    }
)

#: Nomes de `datetime` que carregam instante/fuso — o que não pode vazar.
#: `date` e `timedelta` ficam de fora de propósito: são data-calendário.
_INSTANT_NAMES = frozenset({"datetime", "UTC", "timezone", "tzinfo"})

_PACKAGE_ROOT = Path(quantlab.__file__).parent


def _project_modules() -> list[Path]:
    return sorted(_PACKAGE_ROOT.rglob("*.py"))


def _relative_path(path: Path) -> str:
    return path.relative_to(_PACKAGE_ROOT).as_posix()


def _instant_imports(tree: ast.AST) -> set[str]:
    """Nomes de instante importados de `datetime`, em qualquer forma.

    `import datetime` puro conta como violação: dá acesso a
    `datetime.datetime` sem que a varredura consiga distinguir o uso pelo
    nome importado.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(
                f"import {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] == "datetime"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "datetime":
            found.update(alias.name for alias in node.names if alias.name in _INSTANT_NAMES)
    return found


@pytest.mark.unit
def test_only_the_two_boundary_modules_handle_instants() -> None:
    """A regra em si: nenhum módulo fora da fronteira toca instante ou fuso."""
    offenders = {
        rel: sorted(names)
        for path in _project_modules()
        if (rel := _relative_path(path)) not in _ALLOWED_INSTANT_MODULES
        and (names := _instant_imports(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert offenders == {}, (
        f"módulos manipulando instante fora da fronteira: {offenders}. "
        "A conversão pertence a ingestion/normalizer.py e storage/repository.py "
        "(design v0.3 3.6)."
    )


@pytest.mark.unit
def test_calendar_date_is_allowed_everywhere() -> None:
    """`date`/`timedelta` não são violação — é o vocabulário que RNF-07 exige.

    Sem este teste, alguém "endureceria" a regra acima para o módulo
    `datetime` inteiro e reintroduziria a ambiguidade que a v0.3 corrigiu.
    """
    tree = ast.parse("from datetime import date, timedelta\n")
    assert _instant_imports(tree) == set()


@pytest.mark.unit
def test_both_boundary_modules_actually_handle_instants() -> None:
    """Guarda contra o teste principal passar por os dois terem parado de converter."""
    for relative in _ALLOWED_INSTANT_MODULES:
        path = _PACKAGE_ROOT / relative
        assert _instant_imports(ast.parse(path.read_text(encoding="utf-8"))), (
            f"{relative} deveria manipular instante/fuso e não manipula — "
            "a fronteira declarada em design v0.3 3.6 não existe de verdade."
        )


@pytest.mark.unit
def test_scan_covers_every_subpackage() -> None:
    """Se o glob parar de achar arquivos de algum subpacote, os testes acima passariam vazios."""
    modules = _project_modules()
    names = {_relative_path(path) for path in modules}
    assert names >= _ALLOWED_INSTANT_MODULES

    covered_subpackages = {Path(name).parts[0] for name in names if len(Path(name).parts) > 1}
    for subpackage in ("ingestion", "storage"):
        assert subpackage in covered_subpackages, (
            f"a varredura não alcançou quantlab/{subpackage}/ — "
            "o teste de arquitetura estaria coberto sem estar checando nada"
        )
