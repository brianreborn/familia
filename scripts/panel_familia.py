"""panel_familia.py: familia's pages for the settings panel (code-bootstraps-llama.cpp/scripts/panel.py).

scripts/panel.py (familia's proxy) starts that panel with PANEL_EXTRA pointing here.
These pages hold no rules of their own; they call the same code as the terminal:
  Skills     scripts/skills.py   (refusal(), check_graph_skills(), graph_text_with())
  Licenses   scripts/licenses.py (selection(), accepted(), record(); same acceptance file and hash)
  Hermes     builds the scripts/hermes.sh command line; starts nothing
  Harness2   scripts/harness2.py status / set, when that script is present; never pentest roles
  Models     scripts/validate_graph.py --explain NODE, read-only
Every save goes through the panel's preview page and undo journal. graph.yaml is
edited one line at a time (familia_yaml.set_node_list), so its comments stay.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import familia_yaml  # noqa: E402
import licenses  # noqa: E402
import skills  # noqa: E402

PY = sys.executable or "python3"
H2_MODES = (("off", "Off: Harness2 does nothing (default)"),
            ("propose", "Propose: Harness2 suggests changes; you review each one"),
            ("apply", "Apply: Harness2 applies changes; each one can be reverted"))
CAT_TITLE = {"unknown": "Unknown: no license could be found",
             "restrictive": "Restrictive: limits on how you may use it",
             "custom": "Custom: not a standard open-source license",
             "copyleft": "Copyleft: sharing changes may require sharing source",
             "permissive": "Standard open source (MIT, Apache-2.0, BSD)"}


def _graph():
    try:
        return familia_yaml.load(skills.graph_path()) or {}
    except OSError:
        return {}


def _one(form, key, default=""):
    return (form.get(key) or [default])[0]


def harness2_script():
    p = os.path.join(HERE, "harness2.py")
    return p if os.path.isfile(p) else None


def hermes_modes_supported():
    try:
        with open(os.path.join(HERE, "hermes_harness.py"), encoding="utf-8") as fh:
            t = fh.read()
    except OSError:
        return False
    return "--graph-mode" in t and '"--model"' in t


def h2_mode(a):
    v = (a or {}).get("harness2", (a or {}).get("self_improve"))
    if isinstance(v, dict):
        v = v.get("mode", "propose" if v.get("enabled") else "off")
    return v if v in ("off", "propose", "apply") else "off"


class Pages:
    heading = "familia: skills, licenses, agents and models"

    def __init__(self, ui):
        self.ui = ui

    def pages(self):
        return [
            ("skills", "Skills", "Switch bundled skills on or off for an agent (license-checked)."),
            ("licenses", "Licenses", "Read every license your choices bring, and accept them."),
            ("hermes", "Hermes agent", "Choose one model or the whole graph; get the command to start it."),
            ("harness2", "Harness2 (self-improving harness)", "Off, propose or apply, per agent. Off by default."),
            ("models", "Models and launch parameters", "See each node's model and exact launch flags (read-only)."),
        ]

    # ------------------------------------------------------------ skills
    def _agent(self, g, query):
        agent = _one(query, "agent", "hermes")
        for sec in ("agents", "pentests"):
            if agent in (g.get(sec) or {}):
                return sec, agent, list(((g.get(sec) or {}).get(agent) or {}).get("skills") or [])
        raise ValueError(f"There is no agent or pentest role named {agent!r} in graph.yaml.")

    def _render_skills(self, query, values=None, errors=()):
        ui, g = self.ui, _graph()
        cat = skills.load_catalog()
        src = dict(query)
        if values and values.get("agent"):
            src = {"agent": [values["agent"]]}
        try:
            sec, agent, cur = self._agent(g, src)
        except ValueError as e:
            return ui.error_summary([("", str(e))]) + self._agent_links(g)
        owner = skills.owner_of(g, sec, agent)
        boxes, refused = [], []
        for s in cat.get("skills") or []:
            sid = s["id"]
            on = (values.get("skill." + sid) == "1") if values is not None else sid in cur
            hint = "License: %s. %s. Status: %s." % (ui.esc(s["license"]),
                                                     "Adds tools the agent can run" if s["adds_tools"] else "Instructions only, no tools",
                                                     ui.esc(s["status"]))
            why = skills.refusal(s, sec, owner)
            if why and sid not in cur:
                refused.append("<li><strong>%s</strong>: %s</li>" % (ui.esc(s["name"]), ui.esc(why)))
                continue
            label = "<strong>%s</strong> (%s): %s" % (ui.esc(s["name"]), ui.esc(sid), ui.esc(s["description"]))
            if why:
                hint += " Can't be switched on again once off: " + ui.esc(why)
            boxes.append(ui.checkbox("skill." + sid, label, on, hint))
        kind = "pentest role" if sec == "pentests" else "agent"
        body = ui.hidden("agent", agent)
        body += ui.checkbox_group("Skills for %s %s" % (kind, agent), boxes,
                                  "Ticked means on. Nothing is saved until you confirm on the next page.") if boxes else \
            "<p>No skill can be switched on for this %s.</p>" % kind
        body += "<p>%s %s</p>" % (ui.button("Next: show what will change"), ui.link_button("/", "Cancel"))
        out = ui.error_summary(list(errors))
        out += "<p>Showing skills for the %s <strong>%s</strong>.</p>" % (kind, ui.esc(agent))
        out += ui.form("/p/skills/preview", body)
        if refused:
            out += "<h2>Not available for %s</h2><ul>%s</ul>" % (ui.esc(agent), "".join(refused))
        out += self._agent_links(g, agent)
        return out

    def _agent_links(self, g, current=None):
        ui, rows = self.ui, []
        for sec, what in (("agents", "Agents"), ("pentests", "Pentest roles (never get tool-adding skills)")):
            names = [n for n in (g.get(sec) or {}) if n != current]
            if names:
                rows.append("<h3>%s</h3><ul class=\"pages\">%s</ul>" % (ui.esc(what), "".join(
                    '<li><a href="/p/skills?agent=%s">Skills for %s</a></li>' % (ui.esc(n), ui.esc(n)) for n in names)))
        return ("<h2>Choose another agent</h2>" + "".join(rows)) if rows else ""

    def _skills_plan(self, form):
        g, cat = _graph(), skills.load_catalog()
        sec, agent, cur = self._agent(g, form)
        owner = skills.owner_of(g, sec, agent)
        wanted = [s["id"] for s in cat.get("skills") or [] if _one(form, "skill." + s["id"]) == "1"]
        by_id = {s["id"]: s for s in cat.get("skills") or []}
        errors = []
        for sid in wanted:
            if sid not in cur:
                why = skills.refusal(by_id[sid], sec, owner)
                if why:
                    errors.append(("", why))
        new = [x for x in cur if x in wanted] + [x for x in wanted if x not in cur]
        return g, by_id, sec, agent, cur, new, errors

    def _licenses_html(self, items, only_attention=False):
        ui, groups = self.ui, {}
        for i in items:
            groups.setdefault(i["category"], []).append(i)
        out = []
        for c in sorted(groups, key=licenses.ATTN_ORDER.get):
            if only_attention and c == "permissive":
                out.append("<p>Plus %d item(s) under standard open-source licenses (MIT, Apache-2.0, BSD). "
                           "The full list is on the <a href=\"/p/licenses\">Licenses page</a>.</p>" % len(groups[c]))
                continue
            rows = []
            for i in sorted(groups[c], key=lambda x: (x["license"], x["id"])):
                bits = ["<strong>%s</strong>: %s (%s)" % (ui.esc(i["license"]), ui.esc(i["id"]), ui.esc(i["kind"]))]
                if c != "permissive":
                    bits.append("Used for: " + ui.esc(i["used_for"]))
                    fl = [f for f in i["flags"] if f not in ("unknown",)]
                    if fl:
                        bits.append("Notes: " + ui.esc(", ".join(fl)))
                    if i.get("notes"):
                        bits.append(ui.esc(i["notes"]))
                    for e in i.get("excerpts", []):
                        bits.append("It says: &ldquo;%s&rdquo;" % ui.esc(e))
                    if i.get("text"):
                        bits.append("Full text on this computer: <code>%s</code>" % ui.esc(i["text"]))
                if i.get("link"):
                    bits.append('<a href="%s">Read the license online</a>' % ui.esc(i["link"]))
                rows.append("<li>%s</li>" % "<br>".join(bits))
            out.append("<h3>%s (%d)</h3><ul>%s</ul>" % (ui.esc(CAT_TITLE[c]), len(groups[c]), "".join(rows)))
        return "".join(out)

    def _license_confirms(self, items):
        c = [("accept_licenses", "I have read the licenses listed above and I accept them.")]
        if any(i["category"] == "unknown" for i in items):
            c.append(("accept_unknown", "I also accept the items whose license is unknown (I checked them myself)."))
        return c

    def _skills_preview(self, form):
        g, by_id, sec, agent, cur, new, errors = self._skills_plan(form)
        if errors:
            return {"errors": errors}
        added = [x for x in new if x not in cur]
        changes = ["Switch on %s for %s (license %s)" % (x, agent, by_id[x]["license"]) for x in added]
        changes += ["Switch off %s for %s" % (x, agent) for x in cur if x not in new]
        out = {"changes": changes, "errors": [], "files": [skills.graph_path(), licenses.ACCEPT_FILE],
               "what": "skills for %s: %s" % (agent, "; ".join(changes)),
               "notes": "<p>Saved as <code>%s.%s.skills: [%s]</code> in graph.yaml; its comments are kept. "
                        "Restart the agent (<code>scripts/hermes.sh</code>) to load them.</p>"
                        % (self.ui.esc(sec), self.ui.esc(agent), self.ui.esc(", ".join(new)))}
        if added:
            items, digest = licenses.selection(skills.graph_path(), added)
            if not licenses.accepted(digest, items):
                out["confirm"] = self._license_confirms(items)
                out["notes"] += ("<h2>Licenses you accept by switching these on</h2><p>Items that need your "
                                 "attention come first.</p>" + self._licenses_html(items, only_attention=True))
        return out

    def _skills_apply(self, form):
        g, by_id, sec, agent, cur, new, errors = self._skills_plan(form)
        if errors:
            raise ValueError(errors[0][1])
        added = [x for x in new if x not in cur]
        text = skills.graph_text_with(sec, agent, new)
        if added:
            items, digest = licenses.selection(skills.graph_path(), added)
            if not licenses.accepted(digest, items):
                if _one(form, "accept_licenses") != "1":
                    raise ValueError("Licenses not accepted, so graph.yaml was not changed.")
                unknown = any(i["category"] == "unknown" for i in items)
                if unknown and _one(form, "accept_unknown") != "1":
                    raise ValueError("Some licenses are unknown and were not accepted, so graph.yaml was not changed.")
                licenses.record(digest, items, unknown, "panel")
        p = skills.graph_path()
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, p)
        return "Skills for %s are now: %s. Restart the agent to load them." % (agent, ", ".join(new) or "none")

    # ------------------------------------------------------------ licenses
    def _render_licenses(self, query):
        ui = self.ui
        items, digest = licenses.selection(skills.graph_path())
        ok = licenses.accepted(digest, items)
        n_att = sum(1 for i in items if i["category"] != "permissive")
        status = ("<div class=\"ok\" role=\"status\"><p>You have accepted the licenses of this selection.</p></div>" if ok
                  else "<div class=\"alert\" role=\"status\"><p>Not accepted yet (or something changed since). "
                       "Models, skills and agents will not start until you accept.</p></div>")
        body = ui.hidden("digest", digest)
        body += "<p>%s %s</p>" % (ui.button("Next: accept these licenses") if not ok else "", ui.link_button("/", "Back"))
        return (status + "<p>Using your current selection means agreeing to all %d items below "
                "(%d licenses; %d need your attention and come first). Same list as "
                "<code>scripts/licenses.py review</code>.</p>" % (len(items), len({i['license'] for i in items}), n_att)
                + "<h2>Licenses</h2>" + self._licenses_html(items) + ui.form("/p/licenses/preview", body))

    def _licenses_preview(self, form):
        items, digest = licenses.selection(skills.graph_path())
        if _one(form, "digest") != digest:
            return {"errors": [("", "The selection changed while this page was open. Read the list again.")]}
        if licenses.accepted(digest, items):
            return {"changes": [], "errors": []}
        return {"changes": ["Record that you accept the %d licenses of this selection (hash %s)"
                            % (len({i['license'] for i in items}), digest[:16])],
                "errors": [], "files": [licenses.ACCEPT_FILE], "confirm": self._license_confirms(items),
                "what": "accepted licenses (hash %s)" % digest[:16],
                "notes": "<p>Stored in <code>.cache/familia/license-acceptance.json</code>, the same file "
                         "<code>scripts/licenses.py</code> uses. You are asked again only if the selection changes.</p>"}

    def _licenses_apply(self, form):
        items, digest = licenses.selection(skills.graph_path())
        if _one(form, "digest") != digest:
            raise ValueError("The selection changed while this page was open. Read the list again.")
        unknown = any(i["category"] == "unknown" for i in items)
        if _one(form, "accept_licenses") != "1" or (unknown and _one(form, "accept_unknown") != "1"):
            raise ValueError("Not accepted: tick the boxes on the previous page.")
        licenses.record(digest, items, unknown, "panel")
        return "Licenses accepted."

    # ------------------------------------------------------------ hermes
    def _chat_nodes(self, g):
        out = []
        for name, n in (g.get("nodes") or {}).items():
            if isinstance(n, dict) and n.get("model") and (n.get("role") or name) not in ("embed",) \
                    and "embed" not in str(n.get("role", "")):
                out.append(name)
        return out

    def _render_hermes(self, query):
        ui, g = self.ui, _graph()
        if not hermes_modes_supported():
            return ("<p>This checkout's hermes starts on the graph's coder node only. The choice between one "
                    "model and the whole graph arrives with <code>scripts/hermes.sh --model</code> and "
                    "<code>--graph-mode</code>, which are not in this checkout yet.</p>"
                    "<p>Start it in a terminal:</p>" + ui.pre("scripts/hermes.sh", "Command") +
                    "<p>%s</p>" % ui.link_button("/", "Back"))
        mode = _one(query, "mode", "model")
        nodes = self._chat_nodes(g)
        model = _one(query, "model", "coder" if "coder" in nodes else (nodes[0] if nodes else ""))
        body = ui.radio_group("mode", "How should hermes run?",
                              [("model", "One model: hermes talks to a single node"),
                               ("graph", "The whole graph: hermes uses every node as declared in graph.yaml")],
                              mode, "Nothing starts from this page; it shows the command to run.")
        if nodes:
            body += ui.radio_group("model", "Which model (for One model)", [(n, ui.esc(n)) for n in nodes], model)
        body += "<p>%s %s</p>" % (ui.button("Show the command"), ui.link_button("/", "Back"))
        out = ui.form("/p/hermes", body, method="get")
        if "mode" in query:
            cmd = "scripts/hermes.sh --graph-mode" if mode == "graph" else "scripts/hermes.sh --model %s" % model
            out = ("<h2>Your command</h2><p>Run this in a terminal on this computer. hermes is a terminal "
                   "program, so the panel does not start it for you.</p>" + ui.pre(cmd, "Command")) + out
        return out

    # ------------------------------------------------------------ harness2
    def _h2_agents(self, g):
        return [n for n, a in (g.get("agents") or {}).items() if isinstance(a, dict)]

    def _render_h2(self, query, values=None, errors=()):
        ui, g = self.ui, _graph()
        intro = ("<p>Harness2 is a separate, optional layer. It works with any agent, and hermes runs the "
                 "same with it off. Pentest roles are never offered here.</p>")
        script = harness2_script()
        if not script:
            return (intro + "<div class=\"alert\" role=\"status\"><p>Not available yet: <code>scripts/harness2.py</code> "
                    "is not in this checkout, so there is nothing to switch on. Every agent is off.</p></div>"
                    "<p>%s</p>" % ui.link_button("/", "Back"))
        st = self._run([PY, script, "status"])
        groups = ""
        for name in self._h2_agents(g):
            cur = (values or {}).get("h2." + name) or h2_mode((g.get("agents") or {}).get(name))
            groups += ui.radio_group("h2." + name, "Harness2 for agent %s" % name,
                                     [(v, ui.esc(lab)) for v, lab in H2_MODES], cur)
        body = groups + "<p>%s %s</p>" % (ui.button("Next: show what will change"), ui.link_button("/", "Cancel"))
        return (ui.error_summary(list(errors)) + intro + "<h2>Now</h2>" + ui.pre(st[1] or "(no output)", "Harness2 status")
                + "<h2>Change</h2>" + ui.form("/p/harness2/preview", body))

    def _h2_plan(self, form):
        g = _graph()
        changes, errors, cmds = [], [], []
        pentests = set(g.get("pentests") or {})
        for k in form:
            if k.startswith("h2.") and k[3:] in pentests and k[3:] not in (g.get("agents") or {}):
                errors.append((k, "%s is a pentest role; Harness2 never touches pentest roles." % k[3:]))
        for name in self._h2_agents(g):
            want = _one(form, "h2." + name, "")
            if not want:
                continue
            if want not in [m for m, _ in H2_MODES]:
                errors.append(("h2." + name, "%r is not off, propose or apply." % want))
                continue
            have = h2_mode((g.get("agents") or {}).get(name))
            if want != have:
                changes.append("Harness2 for %s: %s to %s" % (name, have, want))
                cmds.append([PY, harness2_script() or "scripts/harness2.py", "set", "--agent", name, "--mode", want])
        return changes, errors, cmds

    def _h2_preview(self, form):
        if not harness2_script():
            return {"errors": [("", "scripts/harness2.py is not in this checkout yet.")]}
        changes, errors, cmds = self._h2_plan(form)
        shown = "\n".join(" ".join(["python3", "scripts/harness2.py"] + c[2:]) for c in cmds)
        return {"changes": changes, "errors": errors, "files": [skills.graph_path()],
                "what": "Harness2: " + "; ".join(changes),
                "notes": ("<p>The panel runs:</p>" + self.ui.pre(shown, "Commands")) if cmds else ""}

    def _h2_apply(self, form):
        changes, errors, cmds = self._h2_plan(form)
        if errors:
            raise ValueError(errors[0][1])
        for c in cmds:
            rc, out = self._run(c)
            if rc != 0:
                raise ValueError("scripts/harness2.py refused: " + (out.strip().splitlines() or ["exit %d" % rc])[-1])
        return "Harness2 updated: " + "; ".join(changes)

    # ------------------------------------------------------------ models
    def explain(self, node):
        return self._run([PY, os.path.join(HERE, "validate_graph.py"), "--graph", skills.graph_path(),
                          "--explain", node], timeout=120)

    def _render_models(self, query):
        ui, g = self.ui, _graph()
        nodes = g.get("nodes") or {}
        rows = []
        for name, n in nodes.items():
            if not isinstance(n, dict):
                continue
            rows.append("<tr><th scope=\"row\"><a href=\"/p/models?node=%s\">%s</a></th><td>%s</td><td>%s</td><td>%s</td></tr>"
                        % (ui.esc(name), ui.esc(name), ui.esc(n.get("model", "")), ui.esc(n.get("host", "")),
                           ui.esc(n.get("status", ""))))
        out = ""
        node = _one(query, "node")
        if node:
            if node not in nodes:
                out += ui.error_summary([("", "There is no node named %r." % node)])
            else:
                rc, text = self.explain(node)
                out += ("<h2>Launch parameters for %s</h2><p>From <code>scripts/validate_graph.py --explain %s</code>. "
                        "REQUIRED lines must be present or the node is not started.</p>" % (ui.esc(node), ui.esc(node))
                        + ui.pre(text or "(no output)", "Launch parameters for " + node))
                if rc:
                    out += "<p class=\"error\">The check reported a problem (exit %d); see the text above.</p>" % rc
        out += ("<h2>Nodes</h2><p>Read-only. Pick a node name to see its parameters. To change a model, use "
                "<code>scripts/add-model.sh</code> and edit graph.yaml.</p>"
                "<table><caption>Nodes in graph.yaml</caption><thead><tr><th scope=\"col\">Node</th><th scope=\"col\">Model</th>"
                "<th scope=\"col\">Host</th><th scope=\"col\">Status</th></tr></thead><tbody>%s</tbody></table>"
                % "".join(rows))
        return out

    # ------------------------------------------------------------ dispatch
    def _run(self, argv, timeout=60):
        env = dict(os.environ, FAMILIA_NO_TTY="1")
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env, cwd=ROOT,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, "could not run %s: %s" % (os.path.basename(argv[1]), e)
        return r.returncode, (r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")).strip()

    def render(self, page_id, query, values=None, errors=()):
        if page_id == "skills":
            return self._render_skills(query, values, errors)
        if page_id == "licenses":
            return self.ui.error_summary(list(errors)) + self._render_licenses(query)
        if page_id == "harness2":
            return self._render_h2(query, values, errors)
        head = self.ui.error_summary(list(errors))
        if page_id == "hermes":
            return head + self._render_hermes(query)
        return head + self._render_models(query)

    def preview(self, page_id, form):
        try:
            if page_id == "skills":
                return self._skills_preview(form)
            if page_id == "licenses":
                return self._licenses_preview(form)
            if page_id == "harness2":
                return self._h2_preview(form)
        except ValueError as e:
            return {"errors": [("", str(e))]}
        return {"errors": [("", "This page has nothing to save.")]}

    def apply(self, page_id, form):
        if page_id == "skills":
            return self._skills_apply(form)
        if page_id == "licenses":
            return self._licenses_apply(form)
        if page_id == "harness2":
            return self._h2_apply(form)
        raise ValueError("This page has nothing to save.")

    # pages the accessibility check renders besides the plain GET
    def sample_queries(self, page_id):
        g = _graph()
        if page_id == "skills":
            return [{"agent": n} for n in list(g.get("pentests") or {})[:1]]
        if page_id == "hermes":
            return [{"mode": "model", "model": "coder"}, {"mode": "graph"}]
        if page_id == "models" and os.environ.get("PANEL_A11Y_EXPLAIN") == "1":
            return [{"node": next(iter(g.get("nodes") or {"coder": 0}))}]
        return []

    def sample_forms(self, page_id):
        if page_id == "skills":
            return [{"agent": "hermes", "skill.green-probe": "1"}, {"agent": "hermes", "skill.goclaw-skills": "1"}]
        if page_id == "licenses":
            return [{"digest": licenses.selection(skills.graph_path())[1]}]
        return []
