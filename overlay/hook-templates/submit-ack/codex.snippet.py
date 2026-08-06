# --- BEGIN Arborist submit-ack (form B, brand = codex) -----------------------
# Paste verbatim into this brand's UserPromptSubmit hook script, AFTER the hook
# payload has been loaded and BEFORE anything is printed to stdout. Then call it
# once with that payload (see the call at the end of this block; rename `data` to
# whatever the surrounding script calls its payload dict).
#
# Wiring for this brand lives in `.codex/hooks.json`, and this brand's hook
# commands are invoked with `-X utf8` -- keep that when adding a command, so a
# non-ASCII prompt cannot raise a decode error inside the hook.
#
# NOTE, and it is a real finding rather than a shortcut: the shipped per-turn hook
# SCRIPT is byte-identical across both brands (Trellis writes one shared script
# into each brand's hooks directory), so the paste-in body here is the same as the
# other brand's apart from the brand literal. What genuinely differs per brand is
# the wiring file, the `-X utf8` invocation, and the `brand` value below.
#
# Three properties this block must keep, in order of importance:
#   1. It NEVER raises. A failing submit hook blocks a real person's prompt.
#   2. It NEVER writes to stdout. Hook stdout is consumed as context by the host,
#      so a stray print would change what the session sees. Warnings go to stderr.
#   3. It NEVER changes the surrounding script's control flow: no return, no
#      sys.exit, no mutation of the payload.
def _arborist_record_submit_ack(payload, brand="codex"):
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
