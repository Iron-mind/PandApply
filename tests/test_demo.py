from pandapply.demo import run_demo


def test_complete_demo_uses_only_simulated_transports():
    result = run_demo()
    assert result["mode"] == "simulated"
    assert result["jobs"][0] == "MATCHED"
    assert result["jobs"][1] == "SKIPPED_DUPLICATE"
    assert result["receipt"].startswith("sandbox-")
    assert result["mail"] == "interview"
    assert result["reply"].startswith("fake-")
    assert result["replies_sent"] == 1
