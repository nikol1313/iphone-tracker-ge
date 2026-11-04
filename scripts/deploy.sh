#!/usr/bin/env bash
# Update the server to the latest origin/main and restart the changed containers.
# GitHub Actions runs this over SSH after CI passes (see the deploy job in .github/workflows/ci.yml).
# The deploy key is locked to this script in ~/.ssh/authorized_keys, e.g.:
#   command="/home/ubuntu/app/scripts/deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA... github-deploy
# You can also run it by hand on the server.
set -euo pipefail

# Everything is inside main so bash reads the whole script before git pull can rewrite it.
main() {
	cd "$(dirname "$0")/.."

	echo "==> Pulling origin/main"
	git pull --ff-only origin main
	git log --oneline -1

	echo "==> Building and restarting containers"
	# --wait fails the deploy if a container doesn't become healthy.
	docker compose up -d --build --remove-orphans --wait

	# nginx.conf and the Caddyfile are mounted files, so a change to them alone
	# doesn't recreate the containers; reload them so the new config is live.
	docker compose exec -T nginx nginx -s reload
	if docker compose ps --services --status running | grep -qx caddy; then
		docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
	fi

	docker image prune -f >/dev/null
	echo "==> Deployed"
}

main "$@"
exit
