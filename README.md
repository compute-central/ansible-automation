# Ansible Automation

[![CI](https://github.com/compute-central/ansible-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/compute-central/ansible-automation/actions/workflows/ci.yml)
[![ansible-lint: production](https://img.shields.io/badge/ansible--lint-production%20profile-success.svg)](https://ansible.readthedocs.io/projects/lint/profiles/)
[![ansible-core 2.18+](https://img.shields.io/badge/ansible--core-2.18%2B-blue.svg)](https://docs.ansible.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A production-shaped Ansible repository: three environments, three roles, a
rolling canary deployment, a custom module, custom filters, and a Molecule
suite that proves the roles are idempotent.

It is the reference implementation for the
**[Ansible track](https://computecentral.in/ansible/)** on
[Compute Central](https://computecentral.in/), and it passes `ansible-lint`'s
**production** profile with `strict: true` — warnings fail the build.

## Quick Start

```bash
git clone https://github.com/compute-central/ansible-automation.git
cd ansible-automation
./scripts/bootstrap.sh && source .venv/bin/activate

make check     # yamllint + ansible-lint + syntax + unit tests
make dry-run   # converge the dev inventory in check mode, changing nothing
make tags      # everything you can target with --tags
```

The `dev` inventory points at `localhost` over the local connection, so the
whole repository can be exercised in check mode with no infrastructure at all.

## Layout

```
ansible.cfg                  project-local config: pipelining, fact cache, callbacks
requirements.yml             Galaxy collections
requirements.txt             control-node Python deps

inventories/
├── dev/          localhost, hardening off, so a laptop run can't lock you out
├── staging/      two web hosts, 50% batches
└── production/   four web hosts, a canary, 25% batches, confirmation required
     └── group_vars/all/main.yml

playbooks/
├── site.yml        entry point: imports the four below, in order
├── preflight.yml   read-only gate; the production confirmation lives here
├── baseline.yml    the common role everywhere, any_errors_fatal
├── users.yml       service accounts and their individual SSH keys
├── webserver.yml   canary play, then batched rollout
└── health.yml      read-only fleet probe using the custom module

roles/
├── common/     packages, timezone, chrony, sysctl, SSH hardening
├── nginx/      reverse proxy, validated config, reload-not-restart
└── app_user/   accounts, exclusive authorized_keys, validated sudo drop-ins

molecule/default/            Debian 12 and Rocky 9, converged twice for idempotence
├── prepare.yml   waits for systemd to boot before facts are gathered
├── converge.yml  applies the nginx role
└── verify.yml    asserts outcomes, not that Ansible ran

plugins/
├── modules/service_health.py   a custom module, documented and unit tested
└── filter/net_filters.py       four pure filters, unit tested

tests/                       pytest for the module and the filters
```

## Running It

```bash
# Dev, check mode, with a diff of every file that would change
ansible-playbook -i inventories/dev playbooks/site.yml --check --diff

# One concern at a time
ansible-playbook -i inventories/staging playbooks/site.yml --tags ssh,hardening

# Production needs an explicit, typed acknowledgement
ansible-playbook -i inventories/production playbooks/site.yml -e confirm=production

# Read-only health check across the web tier
make health INV=inventories/production
```

## Ideas Worth Stealing

Short version of why the code looks the way it does. Each of these is a thing
that goes wrong in a real fleet.

**Production cannot be reached by accident.** `preflight.yml` asserts
`confirm == env_name` whenever the inventory sets `require_confirmation`. A
muscle-memory `ansible-playbook playbooks/site.yml` cannot converge production
even if the inventory is pointed there. The guard is in a play that touches
nothing, so it fails before the first change.

**One inventory directory per environment.** Not one inventory with
`prod`/`dev` groups. The `-i` flag is then the only thing that decides which
machines are reachable, and there is no group pattern that can straddle two
environments.

**`validate:` on every dangerous template.** The SSH drop-in is checked with
`sshd -t`, the nginx config with `nginx -t -c %s`, the sudoers files with
`visudo -cf`. Ansible renders to a temp file, runs the validator, and only
moves the file into place if it passes. A typo in a sudoers file breaks `sudo`
for every user on the host, including you — that is not a risk worth taking to
save one line of YAML.

**Reload, not restart.** The nginx handler uses `state: reloaded`, which
re-reads the config and hands new connections to new workers while the old ones
drain. A restart drops every in-flight request. Reloading is only safe because
the config was validated first — reloading a broken config leaves the old
workers running and the change silently unapplied.

**Handlers, notified by topic.** Tasks `notify: nginx config changed` rather
than naming a handler. Several tasks can change config and still cause exactly
one reload at the end of the play, and a task does not need to know which
handler implements the restart.

**A canary is a play, not a smaller batch.** `webserver.yml` is two plays: the
canary host alone with `max_fail_percentage: 0`, then the rest in batches. The
split means the canary gets its own verification and its own hold, and a single
bad host stops the run before anything else is touched. `serial: [1, "25%"]` in
one play would not give you that.

**`exclusive: true` on authorized keys.** The `authorized_keys` file ends up
containing exactly the keys listed in the inventory. That is what makes
offboarding actually work: removing a key from the list removes the access,
rather than leaving it in place forever.

**Install a list, not a loop.** `package: name: "{{ list }}"` is one
transaction. A `loop` over the same list is one `dnf` invocation per package —
roughly twenty times slower on a twenty-package host, for identical results.

**`changed_when: false` on anything read-only.** An apt cache refresh changes
nothing on the host. Without this the role is "changed" on every single run,
and once that is true the recap stops carrying any information at all.

**Pipelining is the cheapest speedup there is.** One SSH round trip per task
instead of three, enabled in `ansible.cfg`. It needs `requiretty` off in
sudoers, which is the default on every modern distribution.

**A custom module reports, it does not print.** `plugins/modules/service_health.py`
returns structured data through `exit_json`, declares
`supports_check_mode=True` because probing is read-only, and always reports
`changed=False` because it modifies nothing. Its probe logic is a module-level
function taking explicit arguments, which is what makes it unit testable — a
module whose logic lives only inside `main()` cannot be tested at all.

**Filters raise instead of returning None.** A filter that returns `None` on
bad input produces a config file with a hole in it, and you find out when the
service refuses to start. `upstream_block([])` raises, because an empty nginx
upstream block is a worse error message than ours.

**Molecule runs converge twice.** The `idempotence` step is the one that earns
its CI minutes. A role that reports `changed` on the second run is a role that
restarts a service on every run, forever.

**Verification asserts outcomes.** `molecule/default/verify.yml` checks that
nginx is listening, that the health endpoint returns `ok`, that the default
site is gone, and that `server_tokens` is off. Asserting "the template task
reported changed" would prove nothing.

## Secrets

Nothing in this repository is encrypted, because nothing in it is secret. The
pattern for real secrets:

```bash
# One vault file per environment, next to its group_vars
ansible-vault create inventories/production/group_vars/all/vault.yml

# Reference the vault variable from a plain variable, so the plain file stays
# readable and greppable:
#   app_db_password: "{{ vault_app_db_password }}"

ansible-playbook -i inventories/production playbooks/site.yml \
    -e confirm=production --vault-password-file ~/.vault-pass-prod
```

Keep public SSH keys in plain YAML — they are not secrets, and encrypting them
only makes offboarding harder to review.

## Platform Support

The roles target RHEL 9/10 and Debian/Ubuntu, and `assert` on anything else
rather than guessing. The `common` role branches on `ansible_facts['os_family']`
for service and package names; those differences live in `roles/common/vars/`,
not in `defaults/`, because a caller has no business overriding the name of the
SSH service on RHEL.

The playbooks will refuse to run against macOS — that is the assertion working,
not a bug. Use the Molecule containers or a Linux VM.

## Related

- 📘 [Ansible track](https://computecentral.in/ansible/) — the course this implements
- 🐍 [compute-central/python-automation](https://github.com/compute-central/python-automation) — `opsctl`, a typed and tested ops CLI
- ☸️ [compute-central/kubernetes-platform](https://github.com/compute-central/kubernetes-platform) — manifests, Helm, and GitOps

## License

MIT — see [LICENSE](LICENSE). Fork it, change it, use it at work. Contributions
are not accepted; see [CONTRIBUTING.md](CONTRIBUTING.md).
