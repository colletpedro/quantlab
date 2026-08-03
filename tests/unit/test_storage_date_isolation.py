"""A3 — o tipo `datetime` existe em um lugar só dentro de `storage/`.

Design §3.6 escreve a regra como "`datetime` só aparece em
`ingestion/normalizer.py` e `storage/repository.py`". Ao literal, a regra é
impossível de cumprir: o tipo do domínio é `datetime.date`, que mora no mesmo
módulo da biblioteca padrão — proibir o módulo proibiria o próprio tipo que o
design manda usar em toda parte (a tabela de §3.6 diz "domínio: `datetime.date`
sempre").

A regra implementada aqui é a que o design **quer** dizer: o que não pode
vazar é o instante — a classe `datetime` e o aparato de fuso que vem com ela.
`date` e `timedelta` são vocabulário de data-calendário e são livres.

A ambiguidade está reportada no HANDOFF para a v0.3 do design.

Este é o recorte de storage; a varredura do projeto inteiro é B5 (Bloco B).
"""

import ast
from pathlib import Path

import pytest

import quantlab.storage

#: Único módulo de storage/ autorizado a manipular instantes (design §3.6).
_DATE_BOUNDARY_MODULE = "repository.py"

#: Nomes de `datetime` que carregam hora ou fuso. É isto que não pode vazar
#: para fora da fronteira; `date` e `timedelta` ficam de fora da lista porque
#: são data-calendário, que RNF-07 exige em todo o domínio.
_INSTANT_NAMES = frozenset({"datetime", "UTC", "timezone", "tzinfo"})

_STORAGE_ROOT = Path(quantlab.storage.__file__).parent


def _storage_modules() -> list[Path]:
    return sorted(path for path in _STORAGE_ROOT.glob("*.py"))


def _instant_imports(tree: ast.AST) -> set[str]:
    """Nomes de instante importados de `datetime`, em qualquer forma.

    `import datetime` puro conta como violação: dá acesso a `datetime.datetime`
    sem que a varredura consiga distinguir o uso.
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
def test_only_the_repository_handles_instants() -> None:
    """Nenhum módulo de storage/ além do repositório toca `datetime`/fuso."""
    offenders = {
        path.name: sorted(names)
        for path in _storage_modules()
        if path.name != _DATE_BOUNDARY_MODULE
        and (names := _instant_imports(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert offenders == {}, (
        f"módulos de storage/ manipulando instante fora da fronteira: {offenders}. "
        "A conversão date/datetime pertence a repository.py (design 3.6)."
    )


@pytest.mark.unit
def test_calendar_date_is_allowed_outside_the_boundary() -> None:
    """`date` é o tipo do domínio (RNF-07) e não pode ser tratado como violação.

    Sem este teste, alguém "endureceria" a regra acima para o módulo inteiro e
    quebraria o vocabulário que o design manda usar.
    """
    tree = ast.parse("from datetime import date, timedelta\n")
    assert _instant_imports(tree) == set()


@pytest.mark.unit
def test_the_repository_actually_is_the_boundary() -> None:
    """Guarda contra o teste principal passar por o repositório ter parado de converter."""
    repository = _STORAGE_ROOT / _DATE_BOUNDARY_MODULE
    assert _instant_imports(ast.parse(repository.read_text(encoding="utf-8")))


@pytest.mark.unit
def test_scan_actually_sees_the_storage_modules() -> None:
    """Se o glob parar de achar arquivos, os testes acima passariam vazios."""
    names = {path.name for path in _storage_modules()}
    assert _DATE_BOUNDARY_MODULE in names
    assert len(names) >= 3
