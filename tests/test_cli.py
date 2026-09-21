"""CLI smoke tests."""

import pytest

from competitive_intelligence.cli import main


def test_cli_help(capsys: pytest.CaptureFixture[str]) -> None:
    """The documented module command exposes usable help output."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    assert "Competitive pricing and review analysis demo." in capsys.readouterr().out
