from snodas_tools.cli_reference import DOC_PATH, cli_reference


def test_command_reference_is_up_to_date():
    """docs/cli.md must match the command line parser; regenerate with `python -m snodas_tools.cli_reference`."""
    assert DOC_PATH.read_text() == cli_reference(), (
        "docs/cli.md is out of date: run `python -m snodas_tools.cli_reference` and commit the result"
    )


def test_command_reference_covers_every_option():
    text = cli_reference()
    for option in ["--resolution", "--margin", "--temperature-units", "--quiet", "--verbose", "--version", "--delete-raw"]:
        assert f"{option}" in text
