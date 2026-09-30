#!/usr/bin/env bash
# Vikunja task tracker wrapper.
#
# Why this exists rather than raw curl: the token must never appear in a
# command line. Claude Code records every command it runs, so a literal
# `curl -H "Authorization: Bearer tk_..."` would persist the token in the
# session transcript. This reads it from a file instead.
#
# Second job: field projection. Every read path pipes through jq and emits
# only what is needed. Task descriptions are the bulk of the payload and are
# returned ONLY by `show`, so listing the backlog stays cheap in tokens.
set -euo pipefail

CONF="${VIKUNJA_ENV:-$HOME/.config/quickspin/vikunja.env}"
[[ -r "$CONF" ]] || { echo "no config at $CONF (see scripts/track.sh header)" >&2; exit 1; }
# shellcheck source=/dev/null
source "$CONF"
: "${VIKUNJA_URL:?set VIKUNJA_URL in $CONF}"
: "${VIKUNJA_TOKEN:?set VIKUNJA_TOKEN in $CONF}"

api() {
  local method="$1" path="$2"; shift 2
  curl -sS -m 20 -X "$method" \
    -H "Authorization: Bearer $VIKUNJA_TOKEN" \
    -H "Content-Type: application/json" \
    "$VIKUNJA_URL/api/v1$path" "$@"
}

# Vikunja stores descriptions as HTML (the editor is rich text), not markdown.
html2txt() { sed -e 's/<br[^>]*>/\n/g' -e 's/<\/p>/\n/g' -e 's/<[^>]*>//g' \
  -e 's/&nbsp;/ /g' -e 's/&amp;/\&/g' -e 's/&lt;/</g' -e 's/&gt;/>/g'; }

# POST /tasks/{id} is a full-document REPLACE, not a patch — every field left
# out of the body is reset to its zero value. Sending just {"due_date":...}
# wiped the description and priority off four tasks the first time this ran.
# So every mutation must read the task, merge the change, and send the whole
# object back.
patch() {
  local id="$1" merge="$2"
  api GET "/tasks/$id" | jq -c ". + $merge" | api POST "/tasks/$id" -d @-
}

# One line per task: id, priority, title, due date. No description.
LINES='.[] | "#\(.id)\t[P\(.priority // 0)]\t\(.title)\t\(if .due_date and (.due_date|startswith("0001")|not) then (.due_date|.[0:10]) else "-" end)"'

case "${1:-today}" in
  today)
    # Open, due before end of today (so overdue is included). Vikunja date
    # math: now/d is midnight today, +1d makes it end of today.
    api GET "/tasks" --get \
      --data-urlencode 'filter=done = false && due_date < now/d+1d' \
      --data-urlencode 'sort_by=due_date' --data-urlencode 'order_by=asc' \
      --data-urlencode 'per_page=50' | jq -r "$LINES" | column -t -s $'\t'
    ;;
  backlog)
    api GET "/tasks" --get \
      --data-urlencode 'filter=done = false' \
      --data-urlencode 'sort_by=priority' --data-urlencode 'order_by=desc' \
      --data-urlencode 'per_page=50' | jq -r "$LINES" | column -t -s $'\t'
    ;;
  show)
    id="${2:?usage: track.sh show <id>}"
    api GET "/tasks/$id" | jq -r '"#\(.id) \(.title)\nproject=\(.project_id) prio=\(.priority // 0) done=\(.done)\n---"' 
    api GET "/tasks/$id" | jq -r '.description // ""' | html2txt
    ;;
  add)
    # Description comes from a file so long markdown is never echoed into a
    # command line (and thus never into the transcript twice).
    title="${2:?usage: track.sh add \"<title>\" [--project N] [--desc-file F] [--due YYYY-MM-DD] [--prio N]}"
    shift 2; project="${VIKUNJA_PROJECT:-1}"; desc=""; due=""; prio=0
    while [[ $# -gt 0 ]]; do case "$1" in
      --project)   project="$2"; shift 2 ;;
      --desc-file) desc=$(jq -Rs '.' < "$2"); shift 2 ;;
      --due)       due="$2"; shift 2 ;;
      --prio)      prio="$2"; shift 2 ;;
      *) echo "unknown flag $1" >&2; exit 1 ;;
    esac; done
    body=$(jq -nc --arg t "$title" --argjson p "$prio" \
      --arg d "$due" --argjson desc "${desc:-\"\"}" '
      {title:$t, priority:$p, description:$desc}
      + (if $d == "" then {} else {due_date: ($d + "T09:00:00Z")} end)')
    api PUT "/projects/$project/tasks" -d "$body" | jq -r '"created #\(.id) \(.title)"'
    ;;
  done)
    id="${2:?usage: track.sh done <id>}"
    patch "$id" '{"done":true}' | jq -r '"closed #\(.id) \(.title)"'
    ;;
  note)
    id="${2:?usage: track.sh note <id> \"<text>\"}"
    body=$(jq -nc --arg c "<p>${3:?note text required}</p>" '{comment:$c}')
    api PUT "/tasks/$id/comments" -d "$body" | jq -r '"noted on #\(.id // '"$id"')"'
    ;;
  due)
    # Pulling a task into today's view is the core daily action, so it gets a
    # verb. `due <id> today` is the common case; `due <id> clear` drops it back
    # to the backlog. Vikunja clears a date by setting the zero time, not null.
    id="${2:?usage: track.sh due <id> today|YYYY-MM-DD|clear}"
    case "${3:-today}" in
      today) d="$(date +%F)T09:00:00Z" ;;
      clear) d="0001-01-01T00:00:00Z" ;;
      *)     d="${3}T09:00:00Z" ;;
    esac
    patch "$id" "$(jq -nc --arg d "$d" '{due_date:$d}')" \
      | jq -r '"#\(.id) due \(if (.due_date|startswith("0001")) then "cleared" else (.due_date|.[0:10]) end)"'
    ;;
  prio)
    id="${2:?usage: track.sh prio <id> <0-5>}"
    patch "$id" "$(jq -nc --argjson p "${3:?0-5}" '{priority:$p}')" \
      | jq -r '"#\(.id) prio=\(.priority)"'
    ;;
  projects)
    api GET "/projects" | jq -r '.[] | "\(.id)\t\(.title)"' | column -t -s $'\t'
    ;;
  *) sed -n '1,12p' "$0"; echo; echo "commands: today backlog show add due prio done note projects" ;;
esac
