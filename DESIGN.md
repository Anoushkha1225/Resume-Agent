---
name: Technical Precision System
colors:
  surface: '#0c141a'
  surface-dim: '#0c141a'
  surface-bright: '#323a40'
  surface-container-lowest: '#070f15'
  surface-container-low: '#151d22'
  surface-container: '#192126'
  surface-container-high: '#232b31'
  surface-container-highest: '#2e363c'
  on-surface: '#dbe3ec'
  on-surface-variant: '#c0c7d4'
  inverse-surface: '#dbe3ec'
  inverse-on-surface: '#293138'
  outline: '#8b919d'
  outline-variant: '#414752'
  surface-tint: '#a2c9ff'
  primary: '#a2c9ff'
  on-primary: '#00315c'
  primary-container: '#58a6ff'
  on-primary-container: '#003a6b'
  inverse-primary: '#0060aa'
  secondary: '#67df70'
  on-secondary: '#00390d'
  secondary-container: '#27a640'
  on-secondary-container: '#00320a'
  tertiary: '#ffba42'
  on-tertiary: '#432c00'
  tertiary-container: '#da9600'
  on-tertiary-container: '#4f3400'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d3e4ff'
  primary-fixed-dim: '#a2c9ff'
  on-primary-fixed: '#001c38'
  on-primary-fixed-variant: '#004882'
  secondary-fixed: '#83fc89'
  secondary-fixed-dim: '#67df70'
  on-secondary-fixed: '#002105'
  on-secondary-fixed-variant: '#005317'
  tertiary-fixed: '#ffddaf'
  tertiary-fixed-dim: '#ffba42'
  on-tertiary-fixed: '#281800'
  on-tertiary-fixed-variant: '#614000'
  background: '#0c141a'
  on-background: '#dbe3ec'
  surface-variant: '#2e363c'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  code-md:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 16px
  label-caps:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 48px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 32px
---

## Brand & Style

The design system is engineered for the "resume-agent" developer tool, prioritizing high-density information architecture and technical clarity. The brand personality is understated and professional, leaning into a **Minimalist** and **Geist-like** aesthetic that mimics the environment of a code editor or terminal.

The emotional response should be one of "controlled efficiency"—reducing visual noise to focus entirely on the data and workflow. The style avoids all decorative flourishes like gradients or shadows, relying instead on a strict 1px border system and tonal layering to establish hierarchy. This approach ensures the interface feels like a high-performance utility rather than a consumer app.

## Colors

The palette is rooted in a deep, low-fatigue dark mode. The primary background uses a high-contrast charcoal black, with nested surfaces defined by slightly lighter tones and a consistent border color. 

Accent colors are reserved strictly for status indication and primary actions. They use a medium saturation to remain legible against the dark background without causing eye strain. Functional color application:
- **Primary:** Navigation active states and primary CTA.
- **Surface/Border:** Structural containment and separation.
- **Status Tones:** Badges, log levels, and state indicators only.

## Typography

This design system utilizes a dual-font approach to differentiate between UI controls and technical data.

1.  **Inter (Sans-Serif):** Used for all structural UI elements, navigation, headlines, and descriptive text. It provides a clean, modern readability.
2.  **JetBrains Mono (Monospace):** Used for all dynamic data, timestamps, IDs, code snippets, and terminal logs. This distinction helps developers quickly scan for technical values versus interface labels.

Maintain a tight vertical rhythm. Large headlines are rarely used; hierarchy is instead established through font weight and color (Text Primary vs. Text Secondary).

## Layout & Spacing

The layout philosophy follows a **Fluid Grid** model with a base-4 tracking system. The UI is designed for high-density information environments.

- **Grid:** Use a 12-column grid for desktop views.
- **Padding:** Use `md` (16px) for standard container padding. Use `sm` (8px) for condensed lists or toolbars.
- **Margins:** External page margins are wider (`xl`) to allow the technical content to breathe in the center of the viewport.
- **Reflow:** On mobile, columns collapse to a single stack, and internal margins reduce to `md`.

## Elevation & Depth

This design system rejects the use of shadows and blurs. Depth is conveyed exclusively through **Tonal Layers** and **Subtle Outlines**:

- **Level 0 (Background):** `#0d1117` - The main canvas.
- **Level 1 (Surface):** `#161b22` - Used for cards, sidebars, and input fields.
- **Level 2 (Overlay):** `#1c2128` (optional) - Used for modals or tooltips.
- **Borders:** Every interactive element or container must have a `1px solid #30363d` border to define its boundaries.

When an element is hovered, the border color should brighten to `#8b949e` or the primary color to indicate interactivity.

## Shapes

The shape language is rigid and precise. All containers, buttons, and inputs utilize a consistent **6px (0.375rem)** border radius. 

- **Standard Elements:** 6px (e.g., Cards, Buttons, Inputs).
- **Small Elements:** 4px (e.g., Status Badges, Tooltips).
- **Strict Rule:** Never use pill-shaped or fully circular elements unless for user avatars. This maintains the "technical tool" aesthetic.

## Components

### Buttons
- **Primary:** Solid `#58a6ff` background with black text. No shadow.
- **Secondary:** Transparent background, `1px` border `#30363d`, text `#c9d1d9`.
- **Ghost:** No border, text `#8b949e`. Becomes `#c9d1d9` on hover.

### Status Badges
- Small, 4px rounded corners.
- Background: 15% opacity of the status color.
- Text: Full saturation of the status color using `code-sm` typography.

### Input Fields
- Background: `#0d1117` (inset look).
- Border: `1px solid #30363d`.
- Focus State: Border changes to `#58a6ff` with no glow/shadow.

### Cards
- Background: `#161b22`.
- Border: `1px solid #30363d`.
- Header: Separated by a 1px bottom border when internal content is complex.

### Data Tables
- Use `code-md` for row content.
- Headers use `label-caps` in `#8b949e`.
- Row hover: Background changes to `#1c2128`.

### Code Blocks
- Background: `#0d1117`.
- Padding: `16px`.
- Font: `JetBrains Mono`.