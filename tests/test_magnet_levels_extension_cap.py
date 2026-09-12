import magnet_levels


def test_is_beyond_extension_cap_true_above_default_threshold():
    # Рост со 100 до 195 = +95%, выше дефолтного потолка 90%
    assert magnet_levels.is_beyond_extension_cap(window_start_price=100.0, current_price=195.0) is True


def test_is_beyond_extension_cap_false_below_default_threshold():
    # Рост со 100 до 150 = +50%, ниже потолка
    assert magnet_levels.is_beyond_extension_cap(window_start_price=100.0, current_price=150.0) is False


def test_is_beyond_extension_cap_works_for_downward_moves():
    # Падение со 100 до 5 = -95% по модулю, выше потолка
    assert magnet_levels.is_beyond_extension_cap(window_start_price=100.0, current_price=5.0) is True


def test_is_beyond_extension_cap_respects_custom_threshold():
    # 100 -> 185 = +85%
    assert magnet_levels.is_beyond_extension_cap(
        window_start_price=100.0, current_price=185.0, cap_pct=80.0
    ) is True
    assert magnet_levels.is_beyond_extension_cap(
        window_start_price=100.0, current_price=185.0, cap_pct=100.0
    ) is False


def test_is_beyond_extension_cap_false_when_start_price_zero():
    assert magnet_levels.is_beyond_extension_cap(window_start_price=0.0, current_price=100.0) is False
