# Contributing to GUADE

Thanks for helping improve GUADE. The repository is public; outside contributors should use a fork and submit a pull request. Direct pushes to the LeadRescue LLC repository are limited to invited collaborators.

## Before You Start

- Open an issue to discuss larger changes before investing in implementation.
- Keep changes focused and include tests for behavior changes.
- Never include API keys, passwords, private wallet keys, customer data, or local `.guade` files.
- Only contribute code, documentation, and media that you have the right to submit.

## Local Checks

```bash
python3 -m compileall -q workflow_agent
python3 -m pytest -q
node --check web/app.js
git diff --check
```

## Pull Requests

Describe the user problem, the change, and the checks you ran. Include screenshots for dashboard changes when useful. Mark unfinished work clearly and do not claim that integrations have been tested if they have not.

GUADE is proprietary and all rights are reserved by LeadRescue LLC. A pull request does not itself transfer copyright or grant a license. Any contribution that needs to become exclusively owned by LeadRescue LLC requires a separate written agreement before acceptance.
