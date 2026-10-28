# Forgejo / Gitea adapter: STUB (requirements R0). mxOS hosts on Forgejo
# (https://git.mx-os.mx/, announced https://mx-os.mx/posts/2025-06-04-ya_tenemos_forgejo/).
# Needs SWARM_FORGE_URL (e.g. https://git.mx-os.mx) and FORGEJO_TOKEN.
# Mapping (Forgejo API v1, /api/v1; verify against the target instance's /api/swagger):
#   comment     POST /repos/{owner}/{repo}/issues/{n}/comments  {"body": ...}
#   comments    GET  /repos/{owner}/{repo}/issues/{n}/comments  -> [].body
#   runners     no stable list API in all versions; admin UI /admin/actions/runners
#               or `forgejo-runner` side status. Report "unknown" until verified.
#   reg-token   GET  /repos/{owner}/{repo}/actions/runners/registration-token (newer
#               Forgejo/Gitea) or `forgejo actions generate-runner-token` on the server
#   runner      forgejo-runner register --no-interactive --instance URL --token T
#               --name HOST-role --labels swarm-bench:host ; forgejo-runner daemon
#   dispatch    POST /repos/{owner}/{repo}/actions/workflows/{wf}/dispatches (Forgejo >= 9)
_fj_stub() { echo "forgejo adapter: '$1' not implemented yet (stub; see mapping in forge/forgejo.sh)" >&2; return 3; }
forge_comment() { _fj_stub comment; }
forge_comments() { _fj_stub comments; }
forge_runners() { _fj_stub runners; }
forge_reg_token() { _fj_stub reg-token; }
forge_runner_url() { echo "${SWARM_FORGE_URL:?set SWARM_FORGE_URL}/$SWARM_REPO"; }
forge_dispatch() { _fj_stub dispatch; }
