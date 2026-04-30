# Frontend Changes — Dark/Light Theme Toggle

Adds a user-facing toggle that switches the UI between the existing dark theme and a new light theme. The choice persists across reloads.

## Files modified

- `frontend/index.html`
- `frontend/style.css`
- `frontend/script.js`

## 1. `frontend/index.html`

- Added a fixed-position `<button id="themeToggle">` immediately inside `<body>`, before `.container`. It carries `aria-label`, `aria-pressed`, and `title` for accessibility, and is a real `<button>` so Enter/Space activation is native.
- The button contains two inline SVGs — a sun icon (`.theme-icon-sun`) and a moon icon (`.theme-icon-moon`). CSS shows whichever matches the active theme.
- Bumped the asset cache-busting query string from `?v=11` to `?v=12` on both `style.css` and `script.js` so existing browser caches pick up the new files.

## 2. `frontend/style.css`

### Theme variable sets

- The original `:root` variable block is now scoped to `:root, :root[data-theme="dark"]` — dark remains the default.
- Added a parallel `:root[data-theme="light"]` block with light-mode values:
  - `--background: #f8fafc`, `--surface: #ffffff`, `--surface-hover: #e2e8f0`
  - `--text-primary: #0f172a`, `--text-secondary: #475569`
  - `--border-color: #cbd5e1`, `--assistant-message: #e2e8f0`
  - `--shadow` softened, `--welcome-bg: #dbeafe`
  - `--primary-color` / `--primary-hover` / `--user-message` kept as the same blue so the brand accent is consistent across themes.
- Added a new `--code-bg` variable (dark: `rgba(0,0,0,0.2)`, light: `rgba(15,23,42,0.06)`) and switched `.message-content code` and `.message-content pre` to use it. Without this the inline-code background was nearly invisible in light mode.

### Smooth theme transitions

- A shared rule applies a 0.3s ease transition on `background-color`, `color`, and `border-color` to the major surfaces (body, sidebar, chat container, messages, inputs, suggested items, the toggle itself), so theme changes glide rather than snap.

### Toggle button styling

- `.theme-toggle` is `position: fixed; top: 1rem; right: 1rem;` with `z-index: 100` — it floats in the top-right above the layout regardless of viewport size, including mobile.
- Circular 44×44 button using the active theme's `--surface` background and `--border-color`, with `--shadow` for elevation. Hover state lifts (`translateY(-1px)`) and brightens to `--surface-hover`. `:focus-visible` shows the standard `--focus-ring`.
- Both SVGs are absolutely positioned in the same spot. CSS animates `opacity` (0.3s) and `transform` rotation/scale (0.4s) so the icons cross-fade and rotate when the theme flips:
  - Dark theme → moon visible, sun hidden (rotated −90°, scaled down).
  - `:root[data-theme="light"]` swaps which is shown.

## 3. `frontend/script.js`

### Pre-DOMContentLoaded theme bootstrap

- An IIFE at the top of the file runs *before* `DOMContentLoaded`. It reads the saved `theme` from `localStorage`, falls back to the OS-level `prefers-color-scheme: light` media query, and otherwise defaults to dark. It then sets `data-theme` on `<html>` immediately. This avoids a flash of the wrong theme on first paint.
- The `localStorage` access is wrapped in `try/catch` so privacy/sandbox modes don't break the page.

### `themeToggle` wiring

- Added `themeToggle` to the DOM-element variable list and grab it inside the existing `DOMContentLoaded` handler.
- New `syncThemeToggleState()` keeps `aria-pressed` and `aria-label` on the button correct (`"Switch to dark theme"` vs. `"Switch to light theme"`). Called on init and after every toggle.
- New `toggleTheme()` flips `data-theme` between `light` and `dark`, persists the choice to `localStorage`, and re-syncs ARIA state. Triggered on the button's `click`. Keyboard activation (Enter/Space) is provided by the browser since it's a real `<button>`.

## Behavior summary

- First load: theme = saved preference → OS preference → dark.
- Click (or Enter/Space on focused) the top-right button: theme flips with a 0.3s color crossfade and the icon rotates/scales between sun and moon.
- Reload: previously chosen theme is restored without flash.
- All existing components (sidebar, chat messages, code blocks, sources, suggested items, input, send button, scrollbars) read from CSS variables and adapt automatically. No element was hardcoded to a single theme.
