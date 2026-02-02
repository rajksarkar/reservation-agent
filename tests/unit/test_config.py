"""Tests for configuration loading."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from reservation_agent.core.config import (
    AgentConfig,
    expand_env_vars,
    load_config,
    process_env_vars,
)


class TestExpandEnvVars:
    def test_expand_dollar_brace_syntax(self):
        os.environ["TEST_VAR"] = "test_value"
        result = expand_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_test_value_suffix"

    def test_expand_dollar_syntax(self):
        os.environ["TEST_VAR2"] = "value2"
        result = expand_env_vars("$TEST_VAR2")
        assert result == "value2"

    def test_missing_var_unchanged(self):
        result = expand_env_vars("${NONEXISTENT_VAR_12345}")
        assert result == "${NONEXISTENT_VAR_12345}"

    def test_no_vars_unchanged(self):
        result = expand_env_vars("no variables here")
        assert result == "no variables here"


class TestProcessEnvVars:
    def test_process_dict(self):
        os.environ["DICT_VAR"] = "dict_value"
        data = {"key": "${DICT_VAR}"}
        result = process_env_vars(data)
        assert result["key"] == "dict_value"

    def test_process_list(self):
        os.environ["LIST_VAR"] = "list_value"
        data = ["${LIST_VAR}", "plain"]
        result = process_env_vars(data)
        assert result == ["list_value", "plain"]

    def test_process_nested(self):
        os.environ["NESTED_VAR"] = "nested_value"
        data = {
            "outer": {
                "inner": "${NESTED_VAR}"
            }
        }
        result = process_env_vars(data)
        assert result["outer"]["inner"] == "nested_value"


class TestLoadConfig:
    def test_load_valid_config(self):
        config_data = {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user@example.com",
                "password": "password123",
            },
            "restaurants": [],
            "credentials": [],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            f.flush()

            config = load_config(f.name)
            assert config.smtp.host == "smtp.example.com"
            assert config.smtp.username == "user@example.com"

        os.unlink(f.name)

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_restaurant_config_parsing(self):
        config_data = {
            "smtp": {
                "host": "smtp.example.com",
                "port": 587,
                "username": "user@example.com",
                "password": "pass",
            },
            "restaurants": [
                {
                    "name": "Test Restaurant",
                    "platform": "resy",
                    "venue_id": "test-restaurant",
                    "party_size": 2,
                    "target_dates": ["2026-03-15"],
                    "preferred_times": ["19:00-20:00"],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            f.flush()

            config = load_config(f.name)
            assert len(config.restaurants) == 1
            assert config.restaurants[0].name == "Test Restaurant"
            assert config.restaurants[0].platform == "resy"

        os.unlink(f.name)


class TestAgentConfig:
    def test_get_credential(self):
        config = AgentConfig(
            smtp={
                "host": "smtp.example.com",
                "port": 587,
                "username": "user@example.com",
                "password": "pass",
            },
            credentials=[
                {"platform": "resy", "username": "resy@example.com", "password": "resy_pass"},
                {"platform": "opentable", "username": "ot@example.com", "password": "ot_pass"},
            ],
        )

        resy_cred = config.get_credential("resy")
        assert resy_cred is not None
        assert resy_cred.username == "resy@example.com"

        ot_cred = config.get_credential("opentable")
        assert ot_cred is not None
        assert ot_cred.username == "ot@example.com"

        missing = config.get_credential("nonexistent")
        assert missing is None
