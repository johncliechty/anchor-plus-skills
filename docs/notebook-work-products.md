# Notebook work products

Anchor turns explicitly designated instructional Python/R sources into Jupyter
notebooks without executing them. Kernels run on the same computer as Anchor;
the browser, including a tablet browser, is only a client.

From the Anchor installation:

```text
python notebook_products.py --root <effort-folder> --source lessons/example.py --what "Example lesson" --step "2"
```

Use `.R` for the local `ir` kernel. UTF-8 sources up to 1 MiB become one verbatim
code cell. The helper preserves the source, writes a portable source/notebook/hash
companion and updates one logical row in `DELIVERABLES.md`
(`What | Where | Date | Step`). Step is a display number or name fragment. Where
names the source; Deliverables, Plan and Files resolve its associated notebook.

Opening/registering never executes cells. Source remains separately downloadable.
Edited notebooks are preserved. Changed sources require explicit `--regenerate`,
which creates a new revision rather than overwriting the previous notebook.
Resolve conflicts/pending receipts before claiming completion. Worktree source,
notebook and companion must reach MAIN and register there before step completion
or worktree removal. A copied subset is not completion.

Do not use HTML token launchers, shell `run:` rows or local-device execution as
the notebook launch path.

## Runtime and proof

The optional `notebook_service.py` foreground service requires a dedicated
non-administrator account, private runtime directory, local Python/R kernels,
Jupyter password, and separate HTTPS/WSS origin. It does not install dependencies,
create accounts, change proxies or adopt unrelated Jupyter processes. Jupyter
owns its login cookie; Anchor never forwards its token. The root is a navigation
boundary, not an OS sandbox: this is trusted single-user, not multi-tenant hosting.

Before saying a notebook runs, open its exact tab through Anchor after Jupyter
login, execute the synthetic Python/R hostname probe, verify the Anchor hostname,
and check service recovery. Creating an ipynb alone proves none of these.

Ship generic helpers/instructions and synthetic fixtures only. Exclude private
runtime settings, credentials, host-specific kernelspecs, project files, user
journals and deployment receipts. Collaborators configure their own account,
root, origin and kernels. Additional runners/formats remain future work.
