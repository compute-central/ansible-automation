"""Unit tests for the custom filters.

Filters are pure functions, so they are the easiest part of an Ansible
repository to test properly -- no containers, no SSH, no Ansible run at all.
There is no excuse for an untested filter.

    pytest tests/
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "filter"))

from ansible.errors import AnsibleFilterError  # noqa: E402

from net_filters import (  # noqa: E402
    FilterModule,
    human_duration,
    split_hostport,
    to_sysctl_lines,
    upstream_block,
)


class TestSplitHostport:
    def test_splits_a_valid_pair(self):
        assert split_hostport("web-1.internal:9000") == {
            "host": "web-1.internal",
            "port": 9000,
        }

    def test_tolerates_surrounding_whitespace(self):
        assert split_hostport("  web-1:80  ")["port"] == 80

    @pytest.mark.parametrize(
        "value",
        ["web-1", "web-1:", ":9000", "web 1:9000", "web-1:abc", "web-1:9000:extra"],
    )
    def test_rejects_malformed_input(self, value):
        with pytest.raises(AnsibleFilterError):
            split_hostport(value)

    @pytest.mark.parametrize("value", ["web-1:0", "web-1:70000"])
    def test_rejects_out_of_range_ports(self, value):
        with pytest.raises(AnsibleFilterError, match="out of range|not in host:port"):
            split_hostport(value)

    def test_rejects_a_non_string(self):
        with pytest.raises(AnsibleFilterError, match="expects a string"):
            split_hostport(9000)


class TestUpstreamBlock:
    def test_renders_one_line_per_server(self):
        rendered = upstream_block(["a:1", "b:2"])
        assert rendered.splitlines() == [
            "server a:1 max_fails=3 fail_timeout=10s;",
            "server b:2 max_fails=3 fail_timeout=10s;",
        ]

    def test_passes_through_tuning_arguments(self):
        rendered = upstream_block(["a:1"], max_fails=1, fail_timeout="5s")
        assert "max_fails=1 fail_timeout=5s;" in rendered

    def test_an_empty_list_is_an_error_not_an_empty_block(self):
        """nginx refuses to start on an empty upstream, with a worse message."""
        with pytest.raises(AnsibleFilterError, match="empty list"):
            upstream_block([])

    def test_one_bad_entry_fails_the_whole_render(self):
        with pytest.raises(AnsibleFilterError, match="host:port"):
            upstream_block(["a:1", "not-valid"])

    def test_rejects_a_non_list(self):
        with pytest.raises(AnsibleFilterError, match="expects a list"):
            upstream_block("a:1")


class TestHumanDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "0s"),
            (5, "5s"),
            (60, "1m"),
            (65, "1m 5s"),
            (3600, "1h"),
            (3725, "1h 2m 5s"),
            (86400, "24h"),
        ],
    )
    def test_formats(self, seconds, expected):
        assert human_duration(seconds) == expected

    def test_accepts_a_numeric_string(self):
        assert human_duration("90") == "1m 30s"

    def test_rejects_negatives_and_nonsense(self):
        with pytest.raises(AnsibleFilterError):
            human_duration(-1)
        with pytest.raises(AnsibleFilterError):
            human_duration("soon")


class TestToSysctlLines:
    def test_output_is_sorted_for_a_stable_diff(self):
        """An unsorted dict means a changed file on every run, and a needless reload."""
        rendered = to_sysctl_lines({"net.ipv4.ip_forward": "0", "net.core.somaxconn": "4096"})
        assert rendered.splitlines() == [
            "net.core.somaxconn = 4096",
            "net.ipv4.ip_forward = 0",
        ]

    def test_rejects_a_non_dict(self):
        with pytest.raises(AnsibleFilterError, match="expects a dict"):
            to_sysctl_lines(["a=b"])


def test_every_filter_is_registered():
    """A filter that is implemented but not registered is invisible to Ansible."""
    registered = FilterModule().filters()
    assert set(registered) == {
        "split_hostport",
        "upstream_block",
        "human_duration",
        "to_sysctl_lines",
    }
    assert all(callable(fn) for fn in registered.values())
