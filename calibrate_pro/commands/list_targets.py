"""What a calibration can be aimed at, printed without opening anything.

The packaged binary requires ``--target``, and the sentence it refuses an
unaimed command line with names this listing. A build that declined the listing
told an operator to run something it would not run, so the two shipped together
or the refusal was a dead end.

Everything printed here is stored data. The presets come from the table the
action layer selects them from, the three axes from the slug tables the session
resolves, and the reference definitions from the target package. Nothing is
observed, and no display is touched.

The listing leads with what a session accepts. Under the reference heading are
the definitions this build carries, some reachable through an axis above and
some not, which is why the heading says so rather than reading as a menu.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from calibrate_pro.commands import banner

#: Under everything an operator can ask for, above the definitions behind them.
REFERENCE_HEADING = "Reference catalogue (definitions; not every one is a selectable value)"


def _print_selectable_targets() -> None:
    """Name every target a session accepts, with what each one asks for."""
    from calibrate_pro.application.actions import PRESET_TARGETS
    from calibrate_pro.commands.session import PRESET_PREFIX

    print("\nTargets a calibration can be set to")
    print(f"  {'name':16s} {'gamut':10s} {'white point':12s} tone response")
    for action_id, (gamut, white_point, tone_response, is_hdr) in sorted(PRESET_TARGETS.items()):
        name = action_id[len(PRESET_PREFIX) :]
        marker = " [HDR]" if is_hdr else ""
        print(f"  {name:16s} {gamut:10s} {white_point:12s} {tone_response}{marker}")


def _print_axis(flag: str, entries: tuple[tuple[str, str], ...]) -> None:
    """List what one axis flag takes, as the value beside what it means."""
    print(f"\n  {flag}")
    for name, label in entries:
        print(f"    {name:16s} {label}")


def _print_selectable_axes() -> None:
    """Name every value the three axis flags take, from the session's own tables.

    The temperature row is a range rather than a name, and it is listed with
    the illuminants because it is the same flag. An operator reading this needs
    to know both spellings reach the white point, and the bound is printed from
    the constants the action checks against.
    """
    from calibrate_pro.application.target_selection import (
        CUSTOM_CCT_MAX_K,
        CUSTOM_CCT_MIN_K,
        selectable_gamuts,
        selectable_tone_responses,
        selectable_white_points,
    )

    print("\nOr compose a target from these three axes")
    _print_axis("--gamut", selectable_gamuts())
    _print_axis(
        "--white-point",
        (
            *selectable_white_points(),
            (
                f"{CUSTOM_CCT_MIN_K}K-{CUSTOM_CCT_MAX_K}K",
                "a colour temperature on the daylight locus, written with its K",
            ),
        ),
    )
    _print_axis("--tone-response", selectable_tone_responses())


def list_targets(args: argparse.Namespace) -> int:
    """List what a target can be set to, then the definitions behind them."""
    from calibrate_pro.targets import (
        get_gamma_presets,
        get_gamut_presets,
        get_luminance_presets,
        get_profile_presets,
        get_whitepoint_presets,
    )

    print(f"\n{banner()}")
    print("=" * 50)
    _print_selectable_targets()
    _print_selectable_axes()
    print(f"\n{REFERENCE_HEADING}")
    print("\nCalibration Profiles")
    for profile in get_profile_presets():
        label = " [HDR]" if profile.is_hdr() else ""
        print(f"  {profile.name:25s} - {profile.description}{label}")
    print("\nWhite Points")
    for whitepoint in get_whitepoint_presets():
        print(f"  {whitepoint.preset.value:15s} ({whitepoint.get_cct():.0f}K)")
    print("\nLuminance")
    for luminance in get_luminance_presets():
        label = " [HDR]" if luminance.is_hdr() else " [SDR]"
        print(f"  {luminance.standard.value:20s} - {luminance.get_peak_luminance():.0f} cd/m2{label}")
    print("\nGamma / EOTF")
    for gamma in get_gamma_presets():
        label = " [HDR]" if gamma.is_hdr() else ""
        print(f"  {gamma.preset.value:15s}{label}")
    print("\nGamuts")
    for gamut in get_gamut_presets():
        label = " [Wide Gamut]" if gamut.is_wide_gamut() else ""
        print(f"  {gamut.preset.value:15s}{label}")
    return 0


def run(args: Sequence[str] | None = None) -> int:
    """The frozen dispatcher's entry point, which takes no arguments of its own."""
    parser = argparse.ArgumentParser(
        prog="list-targets",
        description="List the targets a calibration can be set to, and the axes one is composed from.",
    )
    return list_targets(parser.parse_args(list(args or [])))


__all__ = ["REFERENCE_HEADING", "list_targets", "run"]
