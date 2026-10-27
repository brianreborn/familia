#!/usr/bin/env python3
"""familia_cli.py: the engine behind familia(1). Stdlib only.

Reads the menu table (scripts/menu-items.txt) and the subcommand names (scripts/cli-commands.txt),
so `familia <command>`, `familia help`, the man page and shell completion all come from one source.

  familia_cli.py resolve [--windows] WORD...   -> "item KEY N" | "raw N GATE CMD" | "none"
  familia_cli.py help [--windows] [WORD...]    -> help for every command, or for one
  familia_cli.py names [--windows] [--json]    -> every subcommand and its target
  familia_cli.py man [--check | --write]       -> man/familia.1 (roff) generated from the tables
  familia_cli.py words                         -> first words, for shell completion
  familia_cli.py completion bash               -> a bash completion script
Example: python3 scripts/familia_cli.py help serve
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS = os.path.join(ROOT, "scripts", "menu-items.txt")
NAMES = os.path.join(ROOT, "scripts", "cli-commands.txt")
MAN = os.path.join(ROOT, "man", "familia.1")
BUILTINS = ["help", "list", "run", "search", "menu", "completion"]
PH = re.compile(r"\{([A-Z]+):([^}]*)\}")


def rows(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if line.strip() and not line.startswith("#"):
                out.append(line.split("|"))
    return out


def items():
    out = []
    for f in rows(ITEMS):
        f += [""] * (7 - len(f))
        out.append(dict(key=f[0], group=f[1], label=f[2], cmd=f[3], gate=f[4], need=f[5], win=f[6]))
    return out


def shown(cmd, windows=False):
    if not windows:
        cmd = cmd.replace("PY ", "python3 ").replace("PAGER ", "more ")
        cmd = cmd.replace("INSTALLER", "install/linux/install.sh")
    return PH.sub(lambda m: "<" + m.group(1) + ">", cmd)


def table(windows=False):
    """(names, prefer): names maps a tuple of words to ('item', item) or ('raw', dict); prefer maps key -> words."""
    its = items()
    by_key = {i["key"]: i for i in its}
    avail = lambda i: bool(i["win"] if windows else i["cmd"])
    names, prefer = {}, {}
    for f in rows(NAMES):
        words = tuple(f[0].split())
        if f[1] == "raw":
            f += [""] * (6 - len(f))
            cmd = f[4] if windows else f[2]
            if cmd:
                names[words] = ("raw", dict(cmd=cmd, gate=f[3], summary=f[5], words=words))
        elif f[1] in by_key and avail(by_key[f[1]]):
            names.setdefault(words, ("item", by_key[f[1]]))
            prefer.setdefault(f[1], words)
    shorts = {}
    for i in its:
        shorts.setdefault(i["key"].split(".", 1)[-1], []).append(i)
    for i in its:
        if not avail(i):
            continue
        pre, _, short = i["key"].partition(".")
        names.setdefault((i["key"],), ("item", i))
        if pre not in BUILTINS:  # "help cli" stays "help on cli"
            names.setdefault((pre, short), ("item", i))
        if len(shorts[short]) == 1 and short not in BUILTINS and (short,) not in names:
            names[(short,)] = ("item", i)
        if i["key"] not in prefer:
            if names.get((short,), (None, {}))[1] is i:
                prefer[i["key"]] = (short,)
            else:
                prefer[i["key"]] = (pre, short) if names.get((pre, short), (None, {}))[1] is i else (i["key"],)
    return names, prefer


def resolve(words, windows=False):
    names, _ = table(windows)
    n = 0
    while n < len(words) and not words[n].startswith("-"):
        n += 1
    for k in range(n, 0, -1):
        hit = names.get(tuple(words[:k]))
        if hit:
            return hit, k
    return None, 0


def usage_of(i, words, windows=False):
    vals = " ".join("<" + m.group(1) + ">" for m in PH.finditer(i["win"] if windows else i["cmd"]))
    return " ".join(("familia.cmd" if windows else "familia",) + tuple(words)) + (" " + vals if vals else "") + " [ARG...]"


def help_all(windows=False):
    names, prefer = table(windows)
    exe = "familia.cmd" if windows else "familia"
    out = [f"{exe}: run any familia step from the command line. With no command it opens the menu.",
           "",
           f"Usage: {exe} COMMAND [VALUE...] [ARG...]   values fill <NAME>s in order (or as --flag VALUE);",
           f"       {exe} help COMMAND | COMMAND --help  what a command runs, then the script's own --help",
           f"       {exe} --dry-run COMMAND ...          print the exact command, run nothing",
           f"       {exe} --yes COMMAND ...              accept the license review without a prompt",
           f"       {exe} search WORD [--run N]          find a command; list | run KEY | menu | help --man",
           "Extra ARGs go to the underlying script unchanged. Commands marked * run the license review first.", ""]
    group = None
    for i in items():
        if not (i["win"] if windows else i["cmd"]) or i["key"] not in prefer:
            continue
        if i["group"] != group:
            group = i["group"]
            out.append(group + ":")
        u = usage_of(i, prefer[i["key"]], windows).replace(" [ARG...]", "")[len("familia "):]
        star = "*" if i["gate"] == "lic" else " "
        out.append(f"  {u:<34}{star} {i['label']}")
    out.append("Pass-through (every argument goes to the script):")
    for words, (kind, r) in names.items():
        if kind == "raw":
            out.append(f"  {' '.join(words) + ' ...':<34}{'*' if r['gate'] == 'lic' else ' '} {r['summary']}")
    out += ["", f"Every menu item also works as `{exe} KEY` (see `{exe} list`). Full manual: {'man ./man/familia.1' if not windows else 'man/familia.1'}"]
    return "\n".join(out)


def help_one(words, windows=False):
    hit, k = resolve(words, windows)
    if not hit:
        return None
    kind, r = hit
    if kind == "raw":
        return f"{'familia.cmd' if windows else 'familia'} {' '.join(words[:k])} ARG...: {r['summary']}\n  runs: {shown(r['cmd'], windows)} ARG..."
    i = r
    lines = [usage_of(i, words[:k], windows), f"  {i['label']}  (menu: {i['group']}, key {i['key']})",
             f"  runs: {shown(i['win'] if windows else i['cmd'], windows)}"]
    for m in PH.finditer(i["win"] if windows else i["cmd"]):
        lines.append(f"  <{m.group(1)}>: {m.group(2)}")
    if i["gate"] == "lic":
        lines.append("  Runs the license review first (scripts/licenses.py gate).")
    if i["need"]:
        lines.append(f"  Needs {i['need'].split(':', 1)[1]} (shown as not available until it exists).")
    return "\n".join(lines)


# ---------- man page ----------
def esc(s):
    s = s.replace("\\", "\\e").replace("-", "\\-")
    return ("\\&" + s) if s[:1] in (".", "'") else s


ENV = [
    ("FAMILIA_COLOR", "auto (default), always or never: highlighting of search matches."),
    ("NO_COLOR", "When set, no colors or highlighting anywhere."),
    ("FAMILIA_ACCEPT_LICENSES", "yes accepts the license review without a prompt (the summary is still printed); same as \\-\\-yes."),
    ("FAMILIA_ACCEPT_UNKNOWN_LICENSES", "yes also accepts licenses that could not be determined."),
    ("FAMILIA_LICENSE_ACCEPT_FILE", "Where license acceptance is recorded (default .cache/familia/license\\-acceptance.json)."),
    ("FAMILIA_NO_TTY", "1 makes the menu behave as if there were no terminal (print the items, exit 2)."),
    ("FAMILIA_MENU_PIPE", "1 lets menus read choices from a pipe."),
    ("FAMILIA_GRAPH", "Graph file to use instead of graph.yaml, where the script supports it."),
    ("PYTHON", "Python interpreter (default python3)."),
    ("PAGER", "Pager for the quick start and other text (default more)."),
    ("HF_TOKEN", "Hugging Face token for gated models. Read from the environment only; never printed or written to logs."),
    ("GITHUB_TOKEN", "Used by llama_flags.py for GitHub API limits when set; never printed."),
]
FILES = [
    ("graph.yaml", "The declarative graph: hosts, nodes, models, agents, skills, Harness2 settings."),
    ("scripts/menu\\-items.txt", "The menu table. The menu, this command and this page are generated from it."),
    ("scripts/cli\\-commands.txt", "Subcommand names for familia(1)."),
    ("skills/catalog.json", "The bundled skills catalog (green\\-zkillz)."),
    (".cache/familia/license\\-acceptance.json", "Recorded license acceptance (selection hash and license set)."),
    (".cache/familia/model\\-license\\-acceptance.json", "Per\\-model license acceptance for downloads."),
    ("~/.local/bin/familia", "The 2\\-line shim familia install\\-cli writes ($XDG_BIN_HOME; Termux $PREFIX/bin) that runs this checkout's familia."),
    ("~/.local/state/familia/installed.txt", "Every file familia install\\-cli wrote; familia uninstall\\-cli removes exactly those."),
    ("~/.local/state/familia/monitor\\-events.jsonl", "Monitor event log (deaths, OOM kills)."),
    ("registry/models/", "The model database, one JSON file per model file."),
    ("pins.txt", "Pinned sub\\-projects that scripts/configure.sh checks out."),
]


def man_page():
    names, prefer = table(False)
    o = ['.\\" Generated by scripts/familia_cli.py man --write from scripts/menu-items.txt and',
         '.\\" scripts/cli-commands.txt. Do not edit by hand; tests/test_cli.py checks it is current.',
         '.TH FAMILIA 1 "" "familia" "User Commands"',
         ".SH NAME", "familia \\- topology coordinator for local LLMs on old hardware: menu and command line",
         ".SH SYNOPSIS",
         ".B familia", ".br",
         ".B familia", "[\\fB\\-\\-dry\\-run\\fR] [\\fB\\-\\-yes\\fR] \\fICOMMAND\\fR [\\fIVALUE\\fR...] [\\fIARG\\fR...]", ".br",
         ".B familia help", "[\\fICOMMAND\\fR | \\fB\\-\\-man\\fR]", ".br",
         ".B familia search", "\\fIWORD\\fR [\\fB\\-\\-run\\fR \\fIN\\fR]", ".br",
         ".B familia", "\\fBlist\\fR | \\fBrun\\fR \\fIKEY\\fR | \\fBmenu\\fR | \\fBcompletion bash\\fR",
         ".SH DESCRIPTION",
         "With no arguments, \\fBfamilia\\fR opens the menu, grouped by task, where every item shows the exact command it runs. "
         "Every menu item is also a command: \\fBfamilia\\fR \\fICOMMAND\\fR runs the same command as the menu, with the same "
         "license review and the same prompts. Values the command needs (shown as \\fI<NAME>\\fR) are taken from the arguments in "
         "order, or from the flag that precedes them in the command (for example \\fB\\-\\-agent\\fR \\fIhermes\\fR); missing "
         "values are asked for on a terminal, a default is used when there is one, otherwise the command stops with exit status 2. "
         "Any further arguments are passed to the underlying script unchanged.",
         ".PP", "On Windows the same commands are run with \\fBfamilia.cmd\\fR; commands that only exist on one platform are left out on the other.",
         ".PP", "Commands marked (licenses first) run \\fBscripts/licenses.py gate\\fR before anything is installed, started or fetched. "
         "Nothing is accepted for you: on a terminal you are asked, without one the command stops unless \\fB\\-\\-yes\\fR is given.",
         ".SH COMMANDS"]
    group = None
    for i in items():
        if not i["cmd"] or i["key"] not in prefer:
            continue
        if i["group"] != group:
            group = i["group"]
            o.append(".SS " + esc(group))
        u = usage_of(i, prefer[i["key"]])[len("familia "):].replace(" [ARG...]", "")
        o += [".TP", "\\fB" + esc(u.split(" <")[0]) + "\\fR" + "".join(" \\fI<" + v + "\\fR" for v in u.split(" <")[1:]).replace(">\\fR", ">\\fR"),
              esc(i["label"]) + (" (licenses first)" if i["gate"] == "lic" else "") + ".",
              ".br", "Runs: \\fB" + esc(shown(i["cmd"])) + "\\fR"]
    o.append(".SS Pass\\-through commands")
    for words, (kind, r) in names.items():
        if kind == "raw":
            o += [".TP", "\\fB" + esc(" ".join(words)) + "\\fR \\fIARG\\fR...", esc(r["summary"]) + ".", ".br",
                  "Runs: \\fB" + esc(shown(r["cmd"])) + "\\fR \\fIARG\\fR..."]
    o += [".SS Built\\-in commands",
          ".TP", "\\fBhelp\\fR [\\fICOMMAND\\fR]", "Every command, or what one command runs. \\fBfamilia\\fR \\fICOMMAND\\fR \\fB\\-\\-help\\fR also prints the script's own help.",
          ".TP", "\\fBhelp \\-\\-man\\fR", "Show this manual page.",
          ".TP", "\\fBsearch\\fR \\fIWORD\\fR [\\fB\\-\\-run\\fR \\fIN\\fR]", "Find commands by word in every group (key, label, command, group). In the menu: \\fB/\\fR\\fIword\\fR, \\fB?\\fR\\fIword\\fR, \\fBn\\fR, \\fBN\\fR.",
          ".TP", "\\fBlist\\fR", "Every menu item with its key and command.",
          ".TP", "\\fBrun\\fR \\fIKEY\\fR [\\fIVALUE\\fR...]", "Run one menu item by key.",
          ".TP", "\\fBmenu\\fR", "Open the menu (same as no command).",
          ".TP", "\\fBcompletion bash\\fR", "Print a bash completion script: \\fBeval \"$(familia completion bash)\"\\fR.",
          ".SH OPTIONS",
          ".TP", "\\fB\\-\\-dry\\-run\\fR, \\fB\\-n\\fR", "Before the command: print the exact command (and the license review it would run) and run nothing. "
          "After the command it is passed to the script, which then does its own dry run.",
          ".TP", "\\fB\\-\\-yes\\fR, \\fB\\-y\\fR", "Accept the license review without a prompt. The summary is still printed.",
          ".TP", "\\fB\\-\\-help\\fR, \\fB\\-h\\fR", "Help for familia, or after a command for that command.",
          ".TP", "\\fB\\-\\-list\\fR, \\fB\\-\\-run\\fR \\fIKEY\\fR, \\fB\\-\\-search\\fR \\fIWORD\\fR, \\fB\\-\\-pipe\\fR", "The menu's own options (see familia\\-menu.sh \\-\\-help).",
          ".SH ENVIRONMENT"]
    for k, v in ENV:
        o += [".TP", "\\fB" + esc(k) + "\\fR", v]
    o.append(".SH FILES")
    for k, v in FILES:
        o += [".TP", "\\fI" + k + "\\fR", v]
    o += [".SH EXIT STATUS",
          ".TP", "0", "Success, or for search: something matched.",
          ".TP", "1", "The command failed, the licenses are not accepted, the item is not available yet, or nothing matched a search.",
          ".TP", "2", "Usage error: unknown command or option, a missing required value, or no terminal for a menu or prompt.",
          ".TP", "3", "License review: a license could not be determined and was not explicitly accepted.",
          ".PP", "Otherwise the exit status of the command that ran.",
          ".SH EXAMPLES",
          ".nf",
          "familia                              # the menu",
          "familia help serve                   # what \\(aqfamilia serve\\(aq runs",
          "familia \\-\\-dry\\-run serve coder         # print the command, run nothing",
          "familia licenses review              # every license you would be subject to",
          "familia skills enable green\\-probe \\-\\-dry\\-run",
          "familia model fetch Qwen/Qwen2.5\\-0.5B\\-Instruct\\-GGUF Q4_K_M \\-\\-dry\\-run",
          "familia hermes \\-\\-model coder          # hermes on one model",
          "familia hermes \\-\\-graph\\-mode          # hermes on the whole graph",
          "familia harness2 set hermes propose",
          "familia monitor \\-\\-once",
          "familia search license",
          ".fi",
          ".SH SEE ALSO",
          "QUICKSTART.md, MANUAL.md, docs/commands.md, docs/licenses.md, docs/skills.md, docs/harness2.md, docs/monitoring.md",
          ".br", "https://github.com/brianreborn/familia"]
    return "\n".join(o) + "\n"


def completion_bash():
    return """# bash completion for familia. Load with: eval "$(./familia completion bash)"
_familia() {
  local cur=${COMP_WORDS[COMP_CWORD]} root
  root=$(dirname "${COMP_WORDS[0]}")
  if [ "$COMP_CWORD" -eq 1 ]; then
    COMPREPLY=($(compgen -W "$("${PYTHON:-python3}" "$root/scripts/familia_cli.py" words 2>/dev/null)" -- "$cur"))
  else
    COMPREPLY=($(compgen -W "$("${PYTHON:-python3}" "$root/scripts/familia_cli.py" words "${COMP_WORDS[@]:1:COMP_CWORD-1}" 2>/dev/null)" -- "$cur"))
  fi
}
complete -o default -F _familia familia ./familia
"""


def words_after(prefix, windows=False):
    names, _ = table(windows)
    k = len(prefix)
    nxt = {w[k] for w in names if len(w) > k and tuple(w[:k]) == tuple(prefix)}
    if not prefix:
        nxt |= set(BUILTINS)
    return sorted(nxt)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = argv[0], argv[1:]
    windows = "--windows" in rest
    rest = [a for a in rest if a != "--windows"]
    if cmd == "resolve":
        hit, k = resolve(rest, windows)
        if not hit:
            print("none")
        elif hit[0] == "item":
            print(f"item {hit[1]['key']} {k}")
        else:
            print(f"raw {k} {hit[1]['gate'] or '-'} {hit[1]['cmd']}")
        return 0
    if cmd == "help":
        text = help_one(rest, windows) if rest else help_all(windows)
        if text is None:
            exe = "familia.cmd" if windows else "familia"
            print(f"familia: no command '{' '.join(rest)}'. See: {exe} help, or {exe} search WORD", file=sys.stderr)
            return 2
        print(text)
        return 0
    if cmd == "names":
        names, _ = table(windows)
        data = {" ".join(w): (t[1]["key"] if t[0] == "item" else "raw: " + t[1]["cmd"]) for w, t in names.items()}
        print(json.dumps(data, indent=1) if "--json" in rest else "\n".join(f"{w}\t{t}" for w, t in data.items()))
        return 0
    if cmd == "man":
        text = man_page()
        if "--write" in rest:
            os.makedirs(os.path.dirname(MAN), exist_ok=True)
            with open(MAN, "w", encoding="utf-8") as fh:
                fh.write(text)
            return 0
        if "--check" in rest:
            cur = open(MAN, encoding="utf-8").read() if os.path.exists(MAN) else ""
            if cur != text:
                print("man/familia.1 is out of date. Regenerate: python3 scripts/familia_cli.py man --write", file=sys.stderr)
                return 1
            return 0
        sys.stdout.write(text)
        return 0
    if cmd == "words":
        print(" ".join(words_after(rest, windows)))
        return 0
    if cmd == "completion":
        if rest[:1] != ["bash"]:
            print("familia: only bash completion is available: familia completion bash", file=sys.stderr)
            return 2
        sys.stdout.write(completion_bash())
        return 0
    print(f"familia_cli.py: unknown command '{cmd}'. Try --help", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
