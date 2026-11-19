set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -yq --no-install-recommends nginx python3-venv python3-dev build-essential libcurl4-openssl-dev libssl-dev openssl ca-certificates
openssl req -x509 -newkey rsa:2048 -nodes -keyout /etc/nginx/key.pem -out /etc/nginx/cert.pem -days 2 \
  -subj /CN=localhost -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
# Test server: nginx over HTTPS (HTTP/1.1), answers "ok" at once, keeps connections open.
cat > /etc/nginx/sites-enabled/default <<'NG'
server {
  listen 8443 ssl;
  ssl_certificate /etc/nginx/cert.pem;
  ssl_certificate_key /etc/nginx/key.pem;
  keepalive_requests 1000000;
  access_log off;
  location / { return 200 "ok\n"; }
}
NG
systemctl restart nginx
python3 -m venv /root/v
/root/v/bin/pip install -q requests httpx aiohttp niquests urllib3 pycurl curl_cffi
/root/v/bin/pip freeze > /root/exp/versions.txt
curl -s --cacert /etc/nginx/cert.pem https://127.0.0.1:8443/
