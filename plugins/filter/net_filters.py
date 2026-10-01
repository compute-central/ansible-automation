# -*- coding: utf-8 -*-
# Copyright (c) 2026 Sameer Alam
# MIT License (see LICENSE)
"""Custom Jinja2 filters.

A filter is the right tool when a template needs to *transform* data. The wrong
tool is a chain of six built-in filters nobody can read six months later, or a
`set_fact` task that exists only to compute a string.

Filters must be pure: same input, same output, no I/O, no side effects. They
run on the control node during templating, where a network call would silently
serialise the entire play.

Usage:

    {{ ['web-1:9000', 'web-2:9000'] | net_filters.upstream_block }}
    {{ 'web-1:9000' | split_hostport }}
    {{ 300 | human_duration }}
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import re

from ansible.errors import AnsibleFilterError

_HOSTPORT = re.compile(r"^(?P<host>[A-Za-z0-9._-]+):(?P<port>\d{1,5})$")


def split_hostport(value):
    """Split ``host:port`` into a dict, validating both halves.

        {{ 'web-1:9000' | split_hostport }}
        => {'host': 'web-1', 'port': 9000}

    Raising ``AnsibleFilterError`` rather than returning None matters: a filter
    that returns None on bad input produces a config file with a hole in it,
    and the failure surfaces as a service that will not start.
    """
    if not isinstance(value, str):
        raise AnsibleFilterError("split_hostport expects a string, got %s" % type(value).__name__)

    match = _HOSTPORT.match(value.strip())
    if not match:
        raise AnsibleFilterError("%r is not in host:port form" % value)

    port = int(match.group("port"))
    if not 1 <= port <= 65535:
        raise AnsibleFilterError("port %d in %r is out of range" % (port, value))

    return {"host": match.group("host"), "port": port}


def upstream_block(values, max_fails=3, fail_timeout="10s"):
    """Render a list of ``host:port`` strings as nginx upstream server lines.

        {{ app_upstreams | upstream_block(max_fails=2) }}

    Every entry is validated first, so one typo fails the play instead of
    producing an upstream block nginx will reject at reload time.
    """
    if not isinstance(values, (list, tuple)):
        raise AnsibleFilterError(
            "upstream_block expects a list, got %s" % type(values).__name__
        )
    if not values:
        raise AnsibleFilterError("upstream_block was given an empty list")

    lines = []
    for value in values:
        parts = split_hostport(value)
        lines.append(
            "server %s:%d max_fails=%s fail_timeout=%s;"
            % (parts["host"], parts["port"], max_fails, fail_timeout)
        )
    return "\n".join(lines)


def human_duration(seconds):
    """Format a number of seconds as a short human string.

        {{ 3725 | human_duration }}  => '1h 2m 5s'
    """
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        raise AnsibleFilterError("human_duration expects a number, got %r" % (seconds,))

    if total < 0:
        raise AnsibleFilterError("human_duration expects a non-negative number")
    if total == 0:
        return "0s"

    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append("%dh" % hours)
    if minutes:
        parts.append("%dm" % minutes)
    if secs:
        parts.append("%ds" % secs)
    return " ".join(parts)


def to_sysctl_lines(mapping):
    """Render a dict as sysctl.conf lines, sorted for a stable diff.

    Sorting is the point: an unsorted dict produces a different file on every
    run on some Python versions, which shows as a spurious change and a
    needless service reload.
    """
    if not isinstance(mapping, dict):
        raise AnsibleFilterError(
            "to_sysctl_lines expects a dict, got %s" % type(mapping).__name__
        )
    return "\n".join("%s = %s" % (key, mapping[key]) for key in sorted(mapping))


class FilterModule(object):
    """Ansible discovers filters through this class."""

    def filters(self):
        return {
            "split_hostport": split_hostport,
            "upstream_block": upstream_block,
            "human_duration": human_duration,
            "to_sysctl_lines": to_sysctl_lines,
        }
