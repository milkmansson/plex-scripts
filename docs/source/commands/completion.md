# plextool completion

Prints a script that completes plextool's commands, subcommands, options and fixed choices when Tab is pressed.
The script is built from the commands as they are now, so it does not fall behind when a command is added. It needs no
extra package, which also makes it work for a plextool installed with [pipx](https://pipx.pypa.io/stable/).

Handy when:
- The names of commands and options are hard to remember, and `--help` takes longer than a Tab.
- A command with many options, such as `users invite` or `stale`, is being typed.
- A choice that Plex or plextool fixes (such as `--type jwt` or `--downloads yes`) needs completing.

```console
$ eval "$(plextool completion bash)"
$ eval "$(plextool completion zsh)"
```

## Setting it up

There are two ways to load it for bash. The first is to add this line to `~/.bashrc` and open a new shell:

```console
eval "$(plextool completion bash)"
```

That runs plextool at the start of every shell, which took about 0.2 seconds when measured on a development machine.
The second avoids that cost: save the script once, in the place the `bash-completion` package reads completions from
(if that package is installed), or anywhere that `~/.bashrc` then `source`s:

```console
$ plextool completion bash > ~/.local/share/bash-completion/completions/plextool
```

For zsh, add `eval "$(plextool completion zsh)"` to `~/.zshrc`, or save the output to a file and `source` it. The zsh
script loads zsh's `bashcompinit` support first and uses the same logic as the bash one.

A saved script lists the commands as they were when it was saved, so it has to be saved again after plextool is
upgraded and gains a command. The `eval` form always reads the current commands.

## What it completes

| After typing | Tab offers |
| --- | --- |
| `plextool ` | The commands. |
| `plextool token ` | The subcommands (`new`, `list`, `revoke`). |
| `plextool token new --` | The options of that subcommand. |
| `plextool auth login --type ` | The fixed choices for the option (`jwt`, `token`). |
| `plextool token new --file ` | File names, from the shell. |

An option's value is skipped when working out the command, so `plextool stale --library Movies --` offers the
options of `stale`. Values that depend on the server, such as library names and device IDs, are not completed.
