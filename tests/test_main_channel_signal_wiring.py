import inspect

import main


def test_main_source_starts_channel_signal_listener():
    assert "run_channel_signal_listener(" in inspect.getsource(main.main)
