set -e
ulimit -n 65535
/root/v/bin/python /root/exp/http_race.py > /root/exp/results.csv
