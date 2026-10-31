"""Closed vocabularies of IR schema 0.1 (see docs/IR_SPEC.md)."""
from __future__ import annotations

SCHEMA_VERSION = "0.1"

NODE_KINDS = ("box", "text", "image", "icon", "shape", "instance", "slot", "opaque")
ROLES = (
    "none page header footer nav main aside section card list listitem table row cell form button link input "
    "checkbox radio switch select tab tablist heading paragraph label badge avatar logo separator dialog tooltip "
    "menu menuitem toolbar"
).split()
LAYOUT_MODES = ("none", "stack", "flex", "grid", "overlay", "absolute")
OVERLAY_REASONS = ("badge", "popover", "modal", "scrim", "caption", "decoration", "sticky", "floating_action", "other")
ABSOLUTE_REASONS = ("unexplained_residual", "irregular_scatter", "insufficient_evidence")
ALIGN = ("start", "center", "end", "stretch", "baseline")
DISTRIBUTE = ("start", "center", "end", "space-between", "space-around", "space-evenly")
SIZE_KINDS = ("hug", "fill", "fixed", "ratio")
TRACK_KINDS = ("fixed", "share", "content")
FILL_FIT = ("cover", "contain", "stretch", "none")
CLIP = ("none", "clipped", "scroll_hint")
STATUS = ("resolved", "partial", "opaque")
TEXT_STATUS = ("verified", "inferred", "uncertain", "unreadable", "redacted")
PROVENANCE = ("extracted", "reconstructed", "placeholder")
RIGHTS_STATUS = ("unknown", "user_declared", "not_applicable")
ASSET_KINDS = ("raster", "vector", "icon", "logo", "background", "illustration")
PLACEHOLDER_REASONS = ("occluded", "too_small", "not_separable", "unrecoverable")
PLACEHOLDER_KINDS = ("flat", "blurred_palette", "synthesized")
CALIBRATION = ("calibrated", "heuristic", "asserted")
BASIS = ("evidence", "default", "asserted")
EVIDENCE_BASIS = ("measured", "reported", "asserted")
PRODUCER_CLASS = ("classical", "model", "heuristic", "user")
MODE_KINDS = ("light", "dark", "other")
NAV_STATUS = ("unknown", "inferred", "evidenced", "user_asserted")
RELATION_KINDS = ("similar_to", "possible_responsive_variant_of", "shares_layout", "navigates_to")
BREAKPOINT_BASIS = ("interval_midpoint", "convention_snap", "user_specified")
ORIGIN = ("declared", "inferred", "assumed")

EVIDENCE_KINDS = (
    "alignment stack_axis grid_fit spacing_sample size_sample color_sample luminance_profile border_profile "
    "shadow_fit gradient_fit text_metrics repetition containment contrast asset_candidate layout_residual "
    "affordance_cue navigation_cue text_reading element_label user_assertion"
).split()

# R-EPI-4: which evidence kinds may support which claim
ALLOWED_SUPPORTS: dict[str, frozenset[str]] = {
    "structure": frozenset("containment alignment stack_axis grid_fit repetition element_label text_reading asset_candidate user_assertion".split()),
    "role": frozenset("element_label affordance_cue repetition text_reading text_metrics user_assertion".split()),
    "layout": frozenset("alignment stack_axis grid_fit spacing_sample size_sample layout_residual containment repetition asset_candidate user_assertion".split()),
    "style": frozenset("color_sample border_profile shadow_fit gradient_fit text_metrics contrast asset_candidate layout_residual user_assertion".split()),
    "content": frozenset("text_reading asset_candidate user_assertion".split()),
    "realization": frozenset("containment alignment stack_axis grid_fit repetition text_reading asset_candidate user_assertion".split()),
    "token": frozenset("color_sample spacing_sample text_metrics border_profile shadow_fit user_assertion".split()),
    "mode": frozenset("luminance_profile user_assertion".split()),
    "responsive": frozenset("alignment stack_axis grid_fit containment size_sample user_assertion".split()),
    "component": frozenset("repetition user_assertion".split()),
    "relation": frozenset("repetition navigation_cue affordance_cue text_reading user_assertion".split()),
    "asset": frozenset("asset_candidate user_assertion".split()),
}

PATCH_SET_PATH_PREFIXES = (
    "layout.", "size.", "spacing.", "placement.", "style.fill", "style.border", "style.radius",
    "style.shadows", "style.opacity", "text.style", "text.truncation",
)
