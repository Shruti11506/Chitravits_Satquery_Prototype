# Permanent Rule: Lock Theme Transition

## Critical Constraint
**DO NOT MODIFY OR ATTEMPT TO REDESIGN THE SATELLITE ORBIT THEME TRANSITION.**

The theme transition implementation in this repository is strictly finalized, approved, and permanently locked.

### Strictly Locked Files:
1. `src/lib/themeTransition.js`
2. `src/components/ui/ThemeTransitionPattern.jsx`
3. Satellite orbital animation CSS section in `src/index.css` (specifically `::view-transition-group(root)`, `satquery-orbit-scaler`, `satquery-edge-satellite`, `satquery-earth-globe`, and associated modal overlay styles).

### Key Constraints:
- Duration must remain **1600ms** with timing function **`cubic-bezier(0.32, 0, 0.2, 1)`**.
- Uses native View Transitions API circular `clip-path` reveal in lockstep with the multi-tier stepped GPU opacity orbit aura and vector.
- Top layer `<dialog>` promotion via `showModal()`.
- Do NOT rewrite to alternative paths, do NOT alter Bezier curves, and do NOT remove or alter the single expanding orbit wavefront or satellite glide.
