import pytest

from tiksocket import human


@pytest.fixture(autouse=True)
def robot():
    human.configure(enabled=False)
    yield
    human.configure(enabled=False)
