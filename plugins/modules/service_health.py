#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright (c) 2026 Sameer Alam
# MIT License (see LICENSE)
"""A custom module, written the way a module should be written.

Four things make this a module rather than a script wrapped in `command`:

1. **It reports, it does not print.** `module.exit_json()` returns structured
   data that `register` can use. A shell task gives you stdout to parse.
2. **It honours check mode.** Probing is read-only, so it runs under `--check`
   and returns real results instead of skipping.
3. **It never reports a change.** Nothing on the host is modified, so
   ``changed`` is always False. A module that reports a change it did not make
   is what makes `--check` useless and handlers fire for no reason.
4. **It is documented in-tree.** The DOCUMENTATION block below is what
   `ansible-doc service_health` prints, and ansible-lint validates it.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: service_health
short_description: Probe an HTTP endpoint and report whether it is healthy
version_added: "1.0.0"
description:
  - Sends a GET request to a URL and reports the status code, latency, and
    whether the response met the expectations given.
  - Retries transient failures with exponential backoff. A 4xx other than 429
    is not retried, because it will not change on a second attempt.
  - Read-only. The module never modifies the target and never reports a change,
    so it is safe under check mode and in any playbook.
options:
  url:
    description: The URL to probe.
    required: true
    type: str
  expect_status:
    description: The HTTP status code that counts as healthy.
    type: int
    default: 200
  expect_body:
    description: Substring that must appear in the response body, if given.
    type: str
  timeout:
    description: Per-request timeout in seconds.
    type: float
    default: 5.0
  retries:
    description: Total attempts, including the first.
    type: int
    default: 3
  backoff:
    description: Base delay in seconds; doubles on each retry.
    type: float
    default: 0.5
  validate_certs:
    description: Whether to verify TLS certificates. Leave enabled outside labs.
    type: bool
    default: true
  headers:
    description: Extra request headers.
    type: dict
    default: {}
author:
  - Sameer Alam (@sameeralam3127)
"""

EXAMPLES = r"""
- name: Check the local health endpoint
  service_health:
    url: http://127.0.0.1:8080/healthz
    expect_status: 200
    retries: 5
  register: health
  failed_when: false

- name: Fail only once every host has been probed
  ansible.builtin.assert:
    that: health.healthy

- name: Require a specific body
  service_health:
    url: https://api.internal/readyz
    expect_body: '"status":"ok"'
    timeout: 2
"""

RETURN = r"""
healthy:
  description: Whether the endpoint met every expectation.
  returned: always
  type: bool
  sample: true
status_code:
  description: The HTTP status code received, or null if nothing answered.
  returned: always
  type: int
  sample: 200
elapsed_ms:
  description: Round-trip time of the successful attempt, in milliseconds.
  returned: always
  type: float
  sample: 12.4
attempts:
  description: How many requests were sent.
  returned: always
  type: int
  sample: 1
reason:
  description: A short explanation, suitable for a log line.
  returned: always
  type: str
  sample: "expected 200, got 503"
"""

import time

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url

# A 4xx other than 429 will not change on a retry. Retrying it turns one error
# into five and delays the playbook for nothing.
RETRYABLE_STATUSES = frozenset([429, 500, 502, 503, 504])


def probe(module, params):
    """Send up to `retries` requests and return a result dict."""
    attempts = 0
    status_code = None
    elapsed_ms = 0.0
    reason = "no attempt made"
    body = ""

    for attempt in range(1, params["retries"] + 1):
        attempts = attempt
        started = time.time()
        response, info = fetch_url(
            module,
            params["url"],
            method="GET",
            headers=params["headers"],
            timeout=params["timeout"],
        )
        elapsed_ms = (time.time() - started) * 1000.0
        status_code = info.get("status")

        # fetch_url signals a transport failure with a negative status and puts
        # the exception text in info['msg'].
        if status_code is not None and status_code < 0:
            reason = info.get("msg", "connection failed")
            status_code = None
            if attempt < params["retries"]:
                time.sleep(params["backoff"] * (2 ** (attempt - 1)))
                continue
            return False, status_code, elapsed_ms, attempts, reason

        if status_code in RETRYABLE_STATUSES and attempt < params["retries"]:
            reason = "retryable status %s" % status_code
            time.sleep(params["backoff"] * (2 ** (attempt - 1)))
            continue

        if response is not None:
            try:
                body = response.read().decode("utf-8", errors="replace")
            except (AttributeError, OSError):
                body = ""
        break

    if status_code != params["expect_status"]:
        return (
            False,
            status_code,
            elapsed_ms,
            attempts,
            "expected %s, got %s" % (params["expect_status"], status_code),
        )

    if params["expect_body"] and params["expect_body"] not in body:
        return False, status_code, elapsed_ms, attempts, "body did not match"

    return (
        True,
        status_code,
        elapsed_ms,
        attempts,
        "%s in %.0fms" % (status_code, elapsed_ms),
    )


def main():
    module = AnsibleModule(
        argument_spec=dict(
            url=dict(type="str", required=True),
            expect_status=dict(type="int", default=200),
            expect_body=dict(type="str"),
            timeout=dict(type="float", default=5.0),
            retries=dict(type="int", default=3),
            backoff=dict(type="float", default=0.5),
            validate_certs=dict(type="bool", default=True),
            headers=dict(type="dict", default={}),
        ),
        # The module only reads, so it is meaningful under --check rather than
        # being skipped. Declaring this is what tells Ansible that.
        supports_check_mode=True,
    )

    params = module.params
    if params["retries"] < 1:
        module.fail_json(msg="retries must be at least 1")

    healthy, status_code, elapsed_ms, attempts, reason = probe(module, params)

    result = dict(
        # Always False: nothing on the host was modified. Reporting a change
        # here would fire handlers and break --check for every caller.
        changed=False,
        healthy=healthy,
        status_code=status_code,
        elapsed_ms=round(elapsed_ms, 1),
        attempts=attempts,
        reason=reason,
        url=params["url"],
    )
    module.exit_json(**result)


if __name__ == "__main__":
    main()
