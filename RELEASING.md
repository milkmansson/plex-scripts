# Releasing plextool

Releases are published to PyPI by a GitHub Actions workflow
(`.github/workflows/publish.yml`) when a GitHub release is created. It uses
PyPI's trusted publishing, so there are no API tokens to create, store or leak.

| Action on GitHub | What the workflow does |
| --- | --- |
| Create a release marked **pre-release** | Publishes to TestPyPI. |
| Create a full release, or change a pre-release into one | Publishes to PyPI. |

Merging a pull request or pushing a commit does nothing; only a release does.

## One-time setup

### 1. Register the repository as a trusted publisher

Do this on both sites, with the same details. The project does not need to
exist yet: use a *pending publisher*.

- PyPI: <https://pypi.org/manage/account/publishing/>
- TestPyPI: <https://test.pypi.org/manage/account/publishing/>

| Field | Value |
| --- | --- |
| PyPI project name | `plextool` |
| Owner | `milkmansson` |
| Repository name | `plextool` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` on PyPI, `testpypi` on TestPyPI |

### 2. Create the two environments on GitHub

In the repository, go to Settings, then Environments, and create `pypi` and
`testpypi`. For `pypi`, add the releasing account under "Required reviewers" so a full release
waits for approval before anything is uploaded. Adding a reviewer to `testpypi`
too works the same way, but is optional: it is only a rehearsal.

## Making a release

1. Set the version in **both** `pyproject.toml` and `plextool/__init__.py`.
   The workflow stops if they differ, or if they differ from the tag.
2. Commit and merge to `main`.
3. Rehearse on TestPyPI first. On GitHub, create a release with the tag
   `vX.Y.Z` and tick **Set as a pre-release**. If `testpypi` has a required
   reviewer, open the workflow run and approve the deployment. Check the project page at
   <https://test.pypi.org/project/plextool/> and try an install:
   ```console
   $ python3 -m venv /tmp/tt
   $ /tmp/tt/bin/pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple plextool
   $ /tmp/tt/bin/plextool --version
   ```
4. A version number can only be uploaded once to each site, and a deleted
   version can't be reused. If the rehearsal turns up a problem, fix it and
   release the next number.
5. For the real release, edit that same GitHub release, untick **Set as a
   pre-release** and save. GitHub treats that as a full release being created, and the
   workflow publishes to PyPI. Approve the `pypi` environment when GitHub asks.

The workflow runs ruff and the tests, builds the package and checks it with
`twine check` before it publishes anything, and stops if the tag doesn't match the
version in the package.
