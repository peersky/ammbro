# Contributing

Contributions to the paper, pipeline, contracts and figures are welcome through pull requests on
[github.com/peersky/ammbro](https://github.com/peersky/ammbro).

## Before your first pull request

1. **Sign the CLA.** On your first pull request the CLA bot links [`CLA.md`](CLA.md). Sign by
   commenting, stating whom you represent:

   ```
   I have read the CLA Document and I hereby sign the CLA on behalf of myself
   I have read the CLA Document and I hereby sign the CLA on behalf of <legal name of your organisation>
   ```

   A pull request cannot be merged until every contributor to it has signed. Sign again if whom you
   represent changes.
2. **Set up.** Install [uv](https://docs.astral.sh/uv/) and Python ≥ 3.11, then `make setup` and
   `make test`. The paper build needs pandoc ≥ 3, `xelatex` and Graphviz; the gas benchmarks need
   [Foundry](https://getfoundry.sh). See [Reproducing](README.md#reproducing).
3. **RPC is optional.** Every table and figure rebuilds from the JSON committed under `results/`.
   Only re-running extraction needs archive RPC endpoints: copy `.env.example` to `.env` and fill in
   your own. Never commit `.env`. CI on pull requests from forks has no RPC access.

## House rules

- **Results come from code.** Change the study, re-run it, and commit the regenerated
  `results/` JSON and `figures/`. Do not edit numbers in `paper.md` by hand.
- **Paper style.** Define every symbol where it is introduced and never reuse a symbol for a
  second meaning. Cite only sources you have checked, with entries in `references.bib`.
- **Commits.** Pull requests are squash-merged and the maintainer writes the final commit message,
  so your branch's commit messages are free-form. Describe each change in the pull request.

## Licences

Code (`pipeline/`, `contracts/`, `zk/`, `indexer/`, `tools/`, `tests/`, build files) is licensed
under [AGPL-3.0-only](LICENSE). The paper and its material (`paper.md`, `paper.rendered.md`,
`references.bib`, `figures/`, `docs/`, `results/`) is licensed under [CC BY 4.0](LICENSE-CC-BY-4.0).
Your contributions are accepted under these licences and the terms of the [CLA](CLA.md).
