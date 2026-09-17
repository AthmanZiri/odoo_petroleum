# -*- coding: utf-8 -*-
"""Bank statement text parsers.

Adding a bank means writing one module exposing ``parse(text)`` and
``detect(text)``, then adding a single entry to ``PARSERS`` below and to the
``bank`` selection on the wizard.
"""
from . import common
from . import absa
from . import equity
from . import gulf
from . import kcb
from . import premier

from .common import rows_to_csv  # re-exported for the wizard and tests

PARSERS = {
    'absa': absa,
    'kcb': kcb,
    'gulf': gulf,
    'premier': premier,
    'equity': equity,
}

BANK_LABELS = {code: module.BANK_LABEL for code, module in PARSERS.items()}


def parse_statement_text(bank, text):
    """Parse ``text`` with the parser registered for ``bank``."""
    return PARSERS[bank].parse(text)
