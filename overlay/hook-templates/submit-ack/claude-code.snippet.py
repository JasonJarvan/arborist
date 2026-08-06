# --- BEGIN Arborist submit-ack (form B, brand = claude-code) -----------------
# Paste verbatim into this brand's UserPromptSubmit hook script, AFTER the hook
# payload has been loaded and BEFORE anything is printed to stdout. Then call it
# once with that payload (see the call at the end of this block; rename `data` to
# whatever the surrounding script calls its payload dict).
#
# Wiring for this brand lives in `.claude/settings.json` -- or, when that file is
# tracked by the product repo, `.claude/settings.local.json`, because `trellis
# init -y` SKIPS a tracked settings file and installs no hooks at all without
# reporting an error. Form A (a sibling hook command) is preferred; see README.md.
#
# Three properties this block must keep, in order of importance:
#   1. It NEVER raises. A failing UserPromptSubmit hook blocks a real person's
#      prompt. Every path is inside one try/except.
#   2. It NEVER writes to stdout. On this brand, hook stdout becomes injected
#      context, so a stray print would change what the session sees. Warnings go
#      to stderr only.
#   3. It NEVER changes the surrounding script's control flow: no return, no
#      sys.exit, no mutation of the payload.
def _arborist_record_submit_ack(payload, brand="claude-code"):
    """Append a receiver-side ack for every direct-injection envelope submitted.

    Causal evidence: this hook fires only on a real submit, so an ack proves the
    envelope was submitted. Its ABSENCE proves nothing (the module docstring and
    agenttui-registry.md §3 spell out why the fail-safe direction is that way).
    """
    try:
        import importlib.util
        import os
        import sys
        from pathlib import Path

        start = Path(str((payload or {}).get("cwd") or os.getcwd()))
        module_path = None
        for candidate in (start, *start.parents):
            probe = candidate / ".trellis" / "scripts" / "agenttui_submit_ack.py"
            if probe.is_file():
                module_path = probe
                break
        if module_path is None:
            return  # repo has not adopted the ack module; nothing to record
        spec = importlib.util.spec_from_file_location(
            "arborist_submit_ack", module_path
        )
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _records, warnings = module.record_submit_ack(
            payload, receiver_brand=brand
        )
        for warning in warnings:
            print(warning, file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 -- property 1 above
        try:
            import sys

            print(
                f"warning: Arborist submit-ack recording failed ({exc}); "
                f"the prompt itself is unaffected",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001 -- even the warning must not raise
            pass


_arborist_record_submit_ack(data)
# --- END Arborist submit-ack -------------------------------------------------
