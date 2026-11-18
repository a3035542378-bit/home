#!/bin/sh
# Run as root with the path to a new staging directory containing app/ and wx.
set -eu
stage=$(realpath "$1")
app=$stage/app
test -f "$app/ergou/schema.sql"
test -f "$app/deploy/ergou-web.service"
test "$(id -u)" = 0
echo "4bc4d57153536f35a6d98179a2439fe2435b15bbb5ba247254164b92a7f53601  $stage/wx" | sha256sum -c --status
if ! id ergou >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/ergou --no-create-home --shell /usr/sbin/nologin ergou
fi
install -d -m 0700 -o ergou -g ergou /var/lib/ergou /var/lib/ergou/wechat /var/lib/ergou/credentials /var/lib/ergou/login
install -d -m 0755 /opt/ergou/bin /opt/ergou/releases
if ! cmp -s "$stage/wx" /opt/ergou/bin/wx; then
    install -m 0755 "$stage/wx" /opt/ergou/bin/wx.new
    mv -T /opt/ergou/bin/wx.new /opt/ergou/bin/wx
fi
release=$(mktemp -d /opt/ergou/releases/app-XXXXXXXX)
cp -R "$app/." "$release/"
chown -R root:root "$release"
chmod -R u=rwX,go=rX "$release"
ln -s "$release" "$release.next"
mv -Tf "$release.next" /opt/ergou/current
for unit in "$release"/deploy/ergou-*.service; do
    install -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
systemctl daemon-reload
systemctl enable --now ergou-wechat.service
cd /opt/ergou/current
runuser -u ergou -- env HOME=/var/lib/ergou PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m deploy.provision_plugin
db=/var/lib/ergou/ergou.sqlite
if [ ! -e "$db" ]; then
    if [ -f "$stage/features.sqlite" ]; then
        install -m 0600 -o ergou -g ergou "$stage/features.sqlite" "$db.new"
        ln "$db.new" "$db"
        unlink "$db.new"
    fi
fi
runuser -u ergou -- env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m ergou --db "$db" init
systemctl enable ergou-web.service
systemctl restart ergou-web.service
systemctl is-active ergou-wechat.service ergou-web.service
