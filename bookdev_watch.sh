#!/bin/sh
# Prints one "NEW_MSG: {...}" line per new Book Dev message in bookdev/inbox.jsonl.
# Claude runs this under its Monitor tool so Discord messages reach the session.
cd "$(dirname "$0")/bookdev" || exit 1
touch inbox.jsonl
n=$(wc -l < inbox.jsonl)
while true; do
  m=$(wc -l < inbox.jsonl)
  if [ "$m" -gt "$n" ]; then tail -n $((m - n)) inbox.jsonl | sed 's/^/NEW_MSG: /'; n=$m; fi
  [ "$m" -lt "$n" ] && n=$m
  sleep 3
done
