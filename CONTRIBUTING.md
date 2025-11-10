# Contributing to OmniDaemon

Thanks for your interest in contributing! This guide walks you through everything you need to ship changes confidently and help reviewers merge quickly.

---

## 🔧 Local Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/omnirexflora-labs/OmniDaemon.git
   cd OmniDaemon
   ```

2. **Create a feature branch** (never work directly on `main`):
   ```bash
   git checkout -b feature/short-description
   ```

3. **Install dependencies** (requires [uv](https://docs.astral.sh/uv/)):
   ```bash
   uv sync --group dev
   ```

---

## 🧪 Testing & Coverage

- Run the full test suite (unit + integration):
  ```bash
  uv run pytest --cov=src/omnidaemon --cov-report=term --cov-report=json --cov-report=xml -v
  ```

- Every pull request **must maintain ≥70% coverage**. The CI workflow enforces this using `coverage.json` (see `.github/workflows/test.yml`). If coverage drops, the job will fail—add tests before submitting.

- To inspect detailed coverage locally, open `htmlcov/index.html` if you generated an HTML report or review `coverage.json` for per-module stats.

---

## 🧹 Linting & Type Checking

We keep the codebase clean using the same commands CI runs. Execute them before pushing:

```bash
uv run ruff check src/ tests/
uv run black --check src/ tests/
uv run mypy src/
```

If formatting fails (`black --check`), run:
```bash
uv run black src/omnidaemon/cli/main.py  # or the specific file reported
```

Fix any ruff or mypy warnings before opening your PR.

---

## 📝 Commit & PR Guidelines

1. **Keep commits focused.** Small, logical commits are easier to review.
2. **Write descriptive messages.** Summarize intent, e.g. `feat: add redis health endpoint`.
3. **Run tests and linters** before committing (see commands above).
4. **Push your branch** and open a pull request against `main`:
   ```bash
   git push origin feature/short-description
   ```

5. Include in your PR description:
   - What changed and why
   - How you tested it (commands run)
   - Anything reviewers should pay attention to

---

## 🧰 Optional: Pre-commit Hooks

We do not enforce `pre-commit`, but you can install it locally for convenience:

```bash
pip install pre-commit
pre-commit install
```

This will auto-run formatting/linting on staged files before each commit.

---

## ✅ Ready Checklist

Before requesting review, make sure you have:

- [ ] Created and pushed a topic branch (`feature/...`)
- [ ] Run `uv run pytest --cov=...` and verified ≥70% coverage
- [ ] Run `uv run ruff check src/ tests/`
- [ ] Run `uv run black --check src/ tests/`
- [ ] Run `uv run mypy src/`
- [ ] Added tests/docs for any new behavior
- [ ] Updated relevant README/docs if behavior changed

---

## 🙌 Need Help?

Open an issue or start a discussion in the repository. We’re happy to help you get started!

Thanks again for contributing to OmniDaemon and helping build the infrastructure layer for autonomous, event-driven AI systems.
