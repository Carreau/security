# Jupyter security advisory charts

Charts about the security reports (more specifically, GHSAs) we receive across the Jupyter projects

Built on top of [github-security-overview](https://github.com/Yann-P/github-security-overview) which is a cross-organization wrapper around the [GHSA API](https://docs.github.com/en/rest/security-advisories/repository-advisories).

## Prerequisites

Docker, and a GitHub token that can see security advisories in the Jupyter organizations.
If you use the GitHub command line tool, `gh auth token` prints one.

**Without docker**: install github-security-overview first.

## How to run it

```bash
export GITHUB_TOKEN=your-token-here
JUPYTER_PORT=8888 docker compose up --build
```

And click on the link.

The first cell takes a while to fetch data from the API.

## Good to know

The charts are rebuilt from GitHub every time, so the numbers move as new reports come in.

Anything you change in the notebook is saved back to this folder.

The notebook is only reachable from your own computer.

## Maintenance

- Keep the github-security-overview pin up-to-date in the Dockerfile 
- Keep the list of jupyter orgs up to date in the first cell of the notebook.
