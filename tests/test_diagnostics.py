from fitness_mcp.diagnostics import doctor, REQUIRED


def test_missing_configuration_does_not_print_values(monkeypatch, capsys):
    for keys in REQUIRED.values():
        for key in keys:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('SUPABASE_SERVER_KEY', 'do-not-print-this-private-key')
    assert doctor() == 1
    output = capsys.readouterr().out
    assert 'SUPABASE_URL' in output
    assert 'do-not-print-this-private-key' not in output
