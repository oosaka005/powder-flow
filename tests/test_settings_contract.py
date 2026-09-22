from __future__ import annotations

from copy import deepcopy

import pytest

from sila2_servers.powder_characterizer_server.application.characterizer import (
    _assert_same_keys,
)


def test_settings_contract_rejects_new_or_missing_keys() -> None:
    reference = {"material": {"name": "A"}, "manual": {"level": 2}}
    _assert_same_keys(deepcopy(reference), reference)

    with pytest.raises(ValueError, match="keys must remain unchanged"):
        _assert_same_keys({**reference, "i2c_address": "0x60"}, reference)
    with pytest.raises(ValueError, match="keys must remain unchanged"):
        _assert_same_keys({"material": {}, "manual": {"level": 2}}, reference)
