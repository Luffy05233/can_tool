# Using this repository with Codex

Use Luffy05233/can_tool as the repository and main as the starting branch.
AGENTS.md provides the project map, pin assignments, checks and hardware workflow.
docs/bench-status.md preserves the latest debugging observations.

## Prepare a Linux development environment

The firmware and host tools need Python 3, Python venv support, g++ and PlatformIO.
On Debian/Ubuntu, install missing system packages with:

```bash
sudo apt install python3-venv build-essential
```

From the checkout root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
source .venv/bin/activate
./tools/pio run -e master -e slave
python3 -m unittest discover -s test -v
```

The first PlatformIO build downloads the pinned ESP32 platform and toolchain, so
prepare it while network access is available. Activate .venv in each new shell,
or use .venv/bin/python and .venv/bin/pio directly. Full protocol/sanitizer checks
are in [development.md](development.md).

For Codex Cloud, connect/select this GitHub repository and prepare an environment
with these dependencies. Uploading the repository does not itself create or
publish a Codex Cloud environment. Follow the
[official Cloud environments guide](https://learn.chatgpt.com/docs/environments/cloud-environments)
for the current setup flow. Codex reads the root AGENTS.md as project guidance:
[official AGENTS.md documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Cloud development can build firmware and run host tests without the boards.
Flashing and physical CAN tests require a machine with access to the USB devices.
Keep credentials out of the repository; the optional ClickUp integration is not
needed for builds or tests.

## Bundled desktop tools

CANdevStudio-qt6 includes the Qt 6 adaptations and dependency sources, including
changes formerly held inside local submodule checkouts. Build instructions are
in its README.md. linux can tools/can-utils contains the Linux CAN utilities.
These are ordinary source directories in this repository; no recursive submodule
checkout is required. Their licenses remain alongside their sources.
