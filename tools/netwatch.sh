#!/bin/bash
#
# Sample a running fetch's connection, so a stalled stream leaves evidence
# instead of dying with the terminal.
#
#   tools/netwatch.sh [logfile] [process-pattern]
#   tools/netwatch.sh /tmp/fetch.log            # defaults shown below
#
# Run it in a second terminal alongside `brief.py fetch`. Read the result
# against the progress lines in the fetch's own output:
#
#   bytes frozen, peer/addrs unchanged   -> a middlebox reaped the flow state
#   bytes frozen, peer or gw changed     -> handover or address change
#   bytes still climbing                 -> not a stall; a long thinking block
#                                           streams deltas without completing
#                                           a block, so nothing prints
#
# That last case is why this exists. On 2026-09-15 the fetch's progress output
# showed a 123s gap between lines while this sampler showed bytes still
# arriving throughout; the longest real byte-freeze that run was 66s. Trusting
# the progress gaps would have argued for a much longer READ_TIMEOUT than the
# connection actually needs.
#
# Caveats when reading the numbers: samples are 3s apart, and nettop rounds to
# KiB, so a slow trickle can read as flat. Measured freezes are upper bounds.

log="${1:-/tmp/netwatch.log}"
pattern="${2:-brief.py fetch}"

# Derived, not hardcoded: IPv6 and IPv4 default routes can sit on different
# interfaces, and the v6 one is what matters when getaddrinfo prefers v6.
iface6=$(route -n get -inet6 default 2>/dev/null | awk '/interface:/{print $2}')
iface4=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
iface="${iface6:-$iface4}"
[ -z "$iface" ] && { echo "no default route; nothing to sample" >&2; exit 1; }

echo "sampling every 3s -> $log   iface=$iface   pattern='$pattern'   (ctrl-c to stop)"
while :; do
  pid=$(pgrep -f "$pattern" | head -1)
  if [ -z "$pid" ]; then
    printf '%s  (no match for %s)\n' "$(date +%T)" "$pattern"
  else
    # Pick the row whose first field ends in ".<pid>"; "tail -1" catches
    # nettop's own header instead whenever the process has no traffic yet.
    b=$(nettop -P -l 1 -p "$pid" -J bytes_in,bytes_out 2>/dev/null \
        | awk -v p="$pid" '$1 ~ ("\\." p "$") {print $2" "$3" in, "$4" "$5" out"; f=1}
                           END {if (!f) print "no data"}')
    peer=$(lsof -nP -a -p "$pid" -i 2>/dev/null | awk '/ESTABLISHED/{print $9}' | head -1)
    # Every global address, not just the first: macOS keeps a "secured" and a
    # "temporary" v6 address and the socket binds the temporary one, so
    # printing one of them reported the address the connection was not using.
    addrs=$(ifconfig "$iface" 2>/dev/null | awk '
      /inet6 / && $2 !~ /^fe80|^::1/ {printf "%s%s", sep, $2; sep=","}
      /inet / && $2 != "127.0.0.1"   {printf "%s%s", sep, $2; sep=","}')
    gw=$(route -n get -inet6 default 2>/dev/null | awk '/gateway:/{print $2}')
    [ -z "$gw" ] && gw=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')
    printf '%s  %s  peer=%s  addrs=%s  gw=%s\n' \
      "$(date +%T)" "$b" "${peer:-none}" "${addrs:-none}" "${gw:-none}"
  fi
  sleep 3
done | tee -a "$log"
