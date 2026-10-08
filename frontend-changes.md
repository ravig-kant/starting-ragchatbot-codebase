# Frontend Changes: Dark/Light Theme Toggle

## Summary
Added a toggle button that switches between the existing dark theme and a new light theme. Theme switching uses CSS custom properties and a `data-theme` attribute on the `<html>` element.

## Files Changed

### `frontend/index.html`
- Added a small inline script in `<head>` that sets `data-theme` on `<html>` before first paint, so the page never flashes the wrong theme. It uses the saved choice in `localStorage`, falls back to the OS `prefers-color-scheme`, and defaults to dark.
- Added the `#themeToggle` button (`type="button"`, `aria-label`, `title`) at the top of `<body>`. It holds two inline SVG icons, a sun and a moon, both marked `aria-hidden="true"`.
- Bumped the cache-busting versions to `style.css?v=16` and `script.js?v=12`.

### `frontend/style.css`
- **New variables** in `:root` (dark values match the old hardcoded ones): `--code-bg`, `--welcome-shadow`, `--error-color`, `--success-color`, plus `color-scheme: dark`.
- **Light theme** in `:root[data-theme="light"]`:
  - Background `#f1f5f9`, surfaces `#ffffff`, hover surface `#e2e8f0`
  - Primary text `#0f172a`, secondary text `#475569` (both meet WCAG AA on light surfaces)
  - Borders `#cbd5e1`; primary/accent stays `#2563eb` (AA on white)
  - Darker error and success text (`#b91c1c` and `#15803d`) so they stay readable on light backgrounds
  - Softer shadows and code-block background; `color-scheme: light`, so native scrollbars and form controls match
- **Hardcoded colors replaced with variables:** inline code and `pre` backgrounds, the welcome message shadow, and the error/success message text.
- **Bug fix:** the blockquote border used an undefined `var(--primary)`; it now uses `var(--primary-color)`.
- **`.theme-toggle`:** a 40px round button fixed at the top-right. It uses the same surface, border, and hover styles as the rest of the UI (accent border and color, slight lift) and shows a `:focus-visible` focus ring like the other controls.
- **Icon animation:** the sun shows in dark mode and the moon in light mode. They swap with a rotate, scale, and fade transition.
- **Smooth theme transition:** a `.theme-transition` class is added to `<html>` only while switching. It fades background, text, border, and shadow colors over 0.3s. Because it is removed afterwards, the normal hover transitions are unaffected.
- **Reduced motion:** with `prefers-reduced-motion: reduce`, the icon and theme transitions are turned off.

### `frontend/script.js`
- Added a `themeToggle` DOM reference and a click listener.
- `toggleTheme()` flips `data-theme`, briefly applies `.theme-transition`, and saves the choice to `localStorage` (errors are caught in case storage is unavailable).
- `updateThemeToggleLabel()` keeps the button's `aria-label` and `title` describing what the button will do ("Switch to light theme" / "Switch to dark theme").

## Accessibility
- The control is a native `<button>`, so it can be focused with Tab and activated with Enter or Space.
- Its accessible name changes with the current state, and the decorative SVGs are hidden from assistive tech.
- A visible focus ring appears for keyboard users, and reduced-motion preferences are respected.
