"""Tests for CLI commands."""

import pytest
from pathlib import Path
from unittest.mock import patch
from src.cli.main import cli


class TestDeployCommand:
    def test_deploy_valid_manifest(self, tmp_path, capsys):
        """Deploy should succeed when manifest file exists."""
        manifest = tmp_path / "agent.yaml"
        manifest.write_text("name: test-agent")
        with patch("sys.argv", ["cli", "deploy", str(manifest)]):
            cli()
        output = capsys.readouterr().out
        assert "Deploying agent from manifest" in output

    def test_deploy_missing_manifest(self, tmp_path, capsys):
        """Deploy should fail with exit code 1 when manifest does not exist (#131)."""
        manifest = tmp_path / "nonexistent.yaml"
        with patch("sys.argv", ["cli", "deploy", str(manifest)]):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            assert exc_info.value.code == 1
        error = capsys.readouterr().err
        assert "not found" in error

    def test_deploy_directory_instead_of_file(self, tmp_path, capsys):
        """Deploy should fail when manifest path is a directory, not a file (#131)."""
        directory = tmp_path / "manifest_dir"
        directory.mkdir()
        with patch("sys.argv", ["cli", "deploy", str(directory)]):
            with pytest.raises(SystemExit) as exc_info:
                cli()
            assert exc_info.value.code == 1
        error = capsys.readouterr().err
        assert "not a file" in error
