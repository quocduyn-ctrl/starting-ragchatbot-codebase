# Frontend Code Quality Tooling

Adds an automatic-formatting workflow for the frontend (`frontend/index.html`, `frontend/script.js`, `frontend/style.css`) and applies it across the existing files.

The original feature request mentioned `black`, but `black` is a Python formatter and the work was scoped to frontend only — so the frontend equivalent (**Prettier**) was wired up instead. The shape of the workflow (one config file, one format command, one check command) mirrors what `black` would provide on the backend.

## What was added

### 1. `package.json` (new)
Declares Prettier 3.x as the only dev dependency and exposes three npm scripts:
- `npm run format` → `prettier --write` over `frontend/**/*.{html,css,js,json,md}`
- `npm run format:check` → `prettier --check` (non-zero exit on drift; CI-friendly)
- `npm run quality` → alias for `format:check`, intended as the umbrella command if other checks (eslint, stylelint) are added later

### 2. `.prettierrc` (new)
Repo-wide Prettier configuration. Choices made to **minimize churn against the existing codebase**:
- `tabWidth: 4`, `useTabs: false` — matches the existing 4-space indentation in all three frontend files
- `printWidth: 100` — accommodates the wider lines already present (long template literals, fetch calls)
- `singleQuote: true`, `semi: true` — matches existing JS style
- HTML/CSS override `singleQuote: false` (HTML attributes use double quotes by convention)
- JSON/Markdown override `tabWidth: 2` (community standard; Prettier defaults)
- `endOfLine: lf` — enforces LF in the repo regardless of OS, so Windows checkouts don't introduce CRLF diffs

### 3. `.prettierignore` (new)
Excludes:
- `node_modules/`, lock files
- The entire `backend/` tree and any `.py` (Prettier shouldn't touch Python)
- Generated/data dirs (`backend/chroma_db/`, `docs/`, `uploads/`)
- VCS dirs (`.git/`, `.trees/`)
- `CLAUDE.md` and `frontend-changes.md` (project-meta files we don't want auto-reformatted)

### 4. `scripts/format-frontend.sh` (new, executable)
Convenience wrapper: changes to repo root, lazily runs `npm install` if `node_modules/` is missing, then `prettier --write`. Designed so a contributor can clone the repo and run a single command without separately knowing the npm setup steps.

### 5. `scripts/check-quality.sh` (new, executable)
Same lazy-install pattern, but runs `prettier --check`. Exits non-zero if any frontend file is unformatted. Suitable for CI or a pre-push hook. Structured so additional checks (eslint, stylelint, html-validate) can be appended as future quality gates without changing the contract.

### 6. `.gitignore` (updated)
Added a "Node / frontend tooling" section ignoring `node_modules/` and `npm-debug.log*`.

### 7. `README.md` (updated)
New "Frontend Code Quality" section documenting both the shell scripts and the npm scripts, with a note that Node.js is required and `npm install` runs automatically on first invocation.

## Formatting changes applied to existing files

Ran `prettier --write` once. All three frontend files were rewritten:

| File | Lines changed | Nature of changes |
|---|---|---|
| `frontend/index.html` | +110 / −72 (182 changed) | HTML normalization: `<!DOCTYPE>` → `<!doctype>`, self-closing void tags (`<meta ... />`, `<input ... />`, `<link ... />`), consistent indentation under `<html>`/`<head>`/`<body>`, long `<button>` attributes wrapped one-per-line, single-quoted attribute on the suggested-question button that contains a literal `"` |
| `frontend/script.js` | +27 / −27 | Trailing commas in multiline object/array literals (`trailingComma: "es5"`), arrow params parenthesized (`(button) =>`, `(s) =>`, `(title) =>`), removed trailing whitespace, removed double-blank-line, multi-line `.map(...).join(...)` chain reformatted, dropped redundant `else` block formatting |
| `frontend/style.css` | +43 / −26 | Selector lists split one-per-line (`*, *::before, *::after` → 3 lines; same for the markdown header rules), long `font-family` value wrapped, single-quoted strings → double-quoted (CSS convention), inline rules like `font-size: 1.5rem; }` split onto separate lines |

No semantic / behavioral changes — only whitespace, quoting, and line-wrap normalization. The page renders identically.

## Verification

```bash
$ ./scripts/check-quality.sh
==> Prettier format check (frontend/)
Checking formatting...
All matched files use Prettier code style!

All quality checks passed.
```

## How to use going forward

- Before committing frontend changes: `./scripts/format-frontend.sh`
- In CI / pre-push: `./scripts/check-quality.sh`
- IDE integration: most editors auto-pick up `.prettierrc` once the Prettier extension is installed; configure "format on save" against `frontend/`

## Intentionally not done

- **No backend formatter.** The task was scoped to frontend, so Python files (`backend/`) are untouched and explicitly excluded in `.prettierignore`. `black` for the backend would be a separate, parallel addition.
- **No linter** (eslint / stylelint). The task asked for a formatter; lint rules are a heavier change with style debates of their own. The `npm run quality` script is set up as an extension point so a linter can be added later without churn to the script names.
- **No pre-commit hook installed automatically.** `check-quality.sh` is hook-ready; whether to wire it into Husky / a Git hook is left to the team.
