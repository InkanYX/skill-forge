# Imagegen runtime

`image_gen.py` is an unchanged copy of the CLI from the user-provided 2026-11-19 migration package (`runtime/imagegen/scripts/image_gen.py`). Apache-2.0 license is preserved alongside it.

The website invokes it through `app.image_cli_launcher` in a dedicated child process. The launcher supplies a pinned public HTTPS transport, an explicit timeout, and `max_retries=0` to the SDK. The vendor script is not modified. Credentials are supplied only through that child's environment; command arguments and task artifacts contain no credentials.

Run dependencies through the backend's locked environment (`uv sync`). Changes to the runtime require reviewing the execution wrapper and re-running the mocked generate/edit integration tests.
