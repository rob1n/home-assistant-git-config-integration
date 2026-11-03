from __future__ import annotations

import pytest

from .gitrepo import Repos


@pytest.fixture
def repos(tmp_path) -> Repos:
    return Repos(tmp_path)
