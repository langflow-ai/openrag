# Branch Protection Configuration Guide

This guide explains how to configure branch protection rules for the `main` branch to ensure all tests pass before merging.

## Quick Setup

### 1. Navigate to Branch Protection Settings

1. Go to your repository on GitHub
2. Click **Settings** → **Branches**
3. Click **Add rule** or **Edit** for the `main` branch

### 2. Configure Required Settings

Enable the following options:

#### Required Status Checks
[x] **Require status checks to pass before merging**
- [x] Require branches to be up to date before merging
- Required checks:
  - `Test Validation` (from pr-checks.yml)
  - `Run Tests` (from tests.yml)
  - `test-validation` (job name)

#### Additional Protections (Recommended)
- [x] Require a pull request before merging
  - Required approvals: 1 (recommended)
  - Dismiss stale reviews when new commits are pushed
- [x] Require conversation resolution before merging
- [x] Do not allow bypassing the above settings

## CI Workflows Overview

### 1. `tests.yml` - Main Test Workflow

**Triggers:**
- Push to `main` branch
- Pull requests to `main` branch

**Jobs:**
- `test`: Runs unit tests (required to pass)
- `integration-test`: Runs integration tests with OpenSearch (optional)
- `lint`: Code quality checks (optional)
- `test-summary`: Aggregates results

**Required for merge:** [x] Yes (test job must pass)

### 2. `pr-checks.yml` - PR-specific Validation

**Triggers:**
- Pull request opened/updated to `main`

**Jobs:**
- `test-validation`: Strict unit test validation
- `code-quality`: Linting and code quality
- `pr-validation`: Final validation check

**Required for merge:** [x] Yes (test-validation job must pass)

## What Tests Must Pass?

### Required [x]
- All unit tests (77+ tests)
- Runtime: ~2 seconds
- No external dependencies

### Optional [INFO]
- Integration tests (require OpenSearch)
- Linting checks
- Code quality checks

## Test Commands Run in CI

```bash
# Unit tests (REQUIRED - must pass for merge)
uv run pytest tests/ -v \
  -m "not requires_opensearch and not requires_langflow" \
  --cov=src \
  --cov-report=xml \
  --cov-fail-under=1

# Integration tests (OPTIONAL - informational)
uv run pytest tests/ -v \
  -m "integration and requires_opensearch" \
  --cov=src \
  --cov-report=xml
```

## PR Workflow

### Contributor Flow

1. **Create feature branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make changes and run tests locally**
   ```bash
   make test-unit
   ```

3. **Push changes**
   ```bash
   git push origin feature/my-feature
   ```

4. **Create Pull Request**
   - CI automatically runs
   - Status checks appear on PR

5. **Review CI Results**
   - [x] Green checks = ready to merge
   - [FAIL] Red checks = fix issues

6. **Merge when tests pass**
   - All required checks must be green
   - PR can be merged to main

### Status Check Results

#### [x] Success
```
[x] Test Validation
[x] Run Tests
[x] All required tests passed
```
**Action:** PR can be merged

#### [FAIL] Failure
```
[FAIL] Test Validation
[FAIL] Some tests failed
```
**Action:** Fix failing tests and push changes

## Local Testing Before Push

Ensure tests pass locally before pushing:

```bash
# Quick check (recommended)
make test-unit

# Full test suite
make test

# With coverage
make test-coverage

# Specific tests
make test-api
make test-service
```

## Troubleshooting CI Failures

### Tests fail in CI but pass locally

1. **Check Python version**
   ```bash
   python --version  # Should be 3.13
   ```

2. **Ensure dependencies are in sync**
   ```bash
   uv sync --extra dev
   ```

3. **Run tests in CI mode**
   ```bash
   uv run pytest tests/ -v -m "not requires_opensearch and not requires_langflow"
   ```

### Permission errors in CI

- Ensure workflow has necessary permissions
- Check GitHub Actions settings

### Flaky tests

- Integration tests may be flaky (that's why they're optional)
- Unit tests should be stable
- Report flaky tests as issues

## Bypassing Branch Protection (Emergency Only)

[WARN] **Not recommended for normal workflow**

If you're a repository admin and need to bypass:

1. Go to Settings → Branches
2. Temporarily uncheck protection rules
3. Merge PR
4. **Immediately re-enable protection**

[WARN] **Always fix tests instead of bypassing!**

## Configuration Examples

### Minimal Configuration (Recommended)

```yaml
Branch Protection Rules for main:
☑ Require status checks to pass before merging
  ☑ Require branches to be up to date
  Required checks:
    - test-validation
    - Run Tests
☑ Require a pull request before merging
```

### Strict Configuration (Team Environment)

```yaml
Branch Protection Rules for main:
☑ Require status checks to pass before merging
  ☑ Require branches to be up to date
  Required checks:
    - test-validation
    - Run Tests
    - code-quality
☑ Require a pull request before merging
  Number of approvals: 2
  ☑ Dismiss stale reviews
☑ Require conversation resolution
☑ Require signed commits
☑ Include administrators
```

## Monitoring Test Health

### View Test Results

1. **In Pull Request:**
   - Check "Checks" tab
   - View detailed logs
   - See test output

2. **In Actions Tab:**
   - View all workflow runs
   - Check historical pass rates
   - Monitor performance

### Test Metrics

- **Success Rate:** Should be 100% for unit tests
- **Runtime:** ~2 seconds for unit tests
- **Coverage:** Growing toward 70%+

## FAQ

**Q: Can I merge if integration tests fail?**
A: Yes, integration tests are optional. Only unit tests are required.

**Q: How do I skip CI for a commit?**
A: You can't skip required checks. All PRs must pass tests.

**Q: What if tests are flaky?**
A: Fix the flaky tests. Unit tests should never be flaky.

**Q: Can I run CI locally?**
A: Yes, use `make test-unit` to run the same tests CI runs.

**Q: How do I add new required checks?**
A: Update branch protection settings and add job name to required checks.

## Support

- Tests failing? Check test logs in GitHub Actions
- Need help? See `tests/README.md` for testing guide
- Issues? Open a GitHub issue

## Summary

[x] **Required for merge to main:**
1. All unit tests pass (77+ tests)
2. No test failures
3. Code builds successfully

[FAIL] **Blocks merge:**
- Any unit test failure
- Build failures
- Missing required checks

 **Optional:**
- Integration tests
- Linting checks
- Code coverage improvements

Enable branch protection to enforce these rules automatically!
