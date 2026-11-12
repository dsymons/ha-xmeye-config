import pytest
pytest_plugins = "pytest_homeassistant_custom_component"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    yield


@pytest.fixture(autouse=True)
def no_real_broadcast(request):
    """Integration tests shouldn't send real network broadcasts."""
    if "background_discovery" in request.node.name or "broadcast_protocol" in request.node.name:
        yield
        return
    from unittest.mock import patch
    with patch("custom_components.xmeye_config.broadcast_search", return_value=[]):
        yield
