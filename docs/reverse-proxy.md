# Reverse proxy and login

The app has no login of its own. For shared or remote access, run [`docker-compose.yml`](../docker-compose.yml) behind a reverse proxy with an authentication layer, such as Authelia or TinyAuth. The app decides who can edit from the identity the proxy passes along.

← [Back to the README](../README.md) · [Docker hosting](docker.md) · [Configuration reference](configuration.md)

## What the app needs from your proxy

- **Identity headers.** After login, the proxy sends the user's name or email in a `Remote-User` or `Remote-Email` header. Authelia and TinyAuth use these names. Proxies that use other names, such as Authentik (`X-authentik-username`) or oauth2-proxy (`X-Auth-Request-User`), need to copy the value into `Remote-User`.
- **No forged headers.** The proxy must remove any `Remote-User` or `Remote-Email` header the visitor sends, so nobody can claim to be an editor. The examples below remove them on every hostname, before the login adds its own.
- **The proxy's address.** Set `DND_TRACKER_TRUSTED_PROXIES` to the IP the proxy connects from. The app refuses every other client, so people on your network can't skip the login by using the published port directly.

Only the users listed in `DND_TRACKER_ADMINS` can edit. Anyone else who reaches the app can browse, search, export and open linked PDFs.

## Guests and editors on separate hostnames

A setup that works well for a group uses two hostnames for the same app:

| Hostname | Login | Identity headers | Who it's for |
|---|---|---|---|
| `dnd.example.com` | None | Always removed | Players and guests: read-only browsing, no account needed |
| `dndadmin.example.com` | Required | Set by the login | Editors listed in `DND_TRACKER_ADMINS` |

Both route to the same port, so there is still one database. Visitors to the guest hostname never carry an identity, so they're always read-only. On the editor hostname, anyone who logs in but isn't in `DND_TRACKER_ADMINS` is read-only too.

If you don't want public read-only access, use only the editor hostname.

In the examples, the app runs on a host at `192.168.1.10` with the default port `8765`. Replace the hostnames, the address, and the login service with yours.

### Traefik

With the [file provider](https://doc.traefik.io/traefik/providers/file/), for example in a dynamic configuration file:

```yaml
http:
  middlewares:
    strip-identity-headers:
      headers:
        customRequestHeaders:
          Remote-User: ""    # an empty value removes the header
          Remote-Email: ""
    login:
      forwardAuth:
        # Authelia shown; for TinyAuth use http://tinyauth:3000/api/auth/traefik
        address: http://authelia:9091/api/authz/forward-auth
        trustForwardHeader: true
        authResponseHeaders:
          - Remote-User
          - Remote-Email

  routers:
    dnd:
      rule: Host(`dnd.example.com`)
      entryPoints: [websecure]
      tls:
        certResolver: letsencrypt
      middlewares: [strip-identity-headers]
      service: dnd
    dnd-admin:
      rule: Host(`dndadmin.example.com`)
      entryPoints: [websecure]
      tls:
        certResolver: letsencrypt
      middlewares: [strip-identity-headers, login]
      service: dnd

  services:
    dnd:
      loadBalancer:
        servers:
          - url: http://192.168.1.10:8765
```

Set `DND_TRACKER_TRUSTED_PROXIES` to the IP of the Traefik host.

### Caddy

Caddy normally runs `request_header` after `forward_auth`, which would remove the identity the login just added. The `route` block makes the directives run in the order written.

```caddyfile
dnd.example.com {
	request_header -Remote-User
	request_header -Remote-Email
	reverse_proxy 192.168.1.10:8765
}

dndadmin.example.com {
	route {
		request_header -Remote-User
		request_header -Remote-Email
		# Authelia shown; for TinyAuth use: forward_auth tinyauth:3000 { uri /api/auth/caddy ... }
		forward_auth authelia:9091 {
			uri /api/authz/forward-auth
			copy_headers Remote-User Remote-Email
		}
		reverse_proxy 192.168.1.10:8765
	}
}
```

Set `DND_TRACKER_TRUSTED_PROXIES` to the IP of the Caddy host.

### nginx

nginx rejects request bodies over 1 MB by default. Raise `client_max_body_size` so cover uploads (up to 15 MB) work. An empty `proxy_set_header` value removes the header.

```nginx
# Guests: read-only, no login.
server {
    listen 443 ssl;
    server_name dnd.example.com;
    # ssl_certificate and ssl_certificate_key go here.
    client_max_body_size 16m;

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Remote-User "";
        proxy_set_header Remote-Email "";
        proxy_pass http://192.168.1.10:8765;
    }
}

# Editors: login with Authelia.
server {
    listen 443 ssl;
    server_name dndadmin.example.com;
    # ssl_certificate and ssl_certificate_key go here.
    client_max_body_size 16m;

    location / {
        auth_request /internal/authelia/authz;
        auth_request_set $remote_user $upstream_http_remote_user;
        auth_request_set $remote_email $upstream_http_remote_email;
        auth_request_set $redirection_url $upstream_http_location;
        error_page 401 =302 $redirection_url;

        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Replaces anything the visitor sent with the identity from the login.
        proxy_set_header Remote-User $remote_user;
        proxy_set_header Remote-Email $remote_email;
        proxy_pass http://192.168.1.10:8765;
    }

    location = /internal/authelia/authz {
        internal;
        proxy_pass http://authelia:9091/api/authz/auth-request;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-Method $request_method;
        proxy_set_header X-Original-URL $scheme://$http_host$request_uri;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

Set `DND_TRACKER_TRUSTED_PROXIES` to the IP of the nginx host. Nginx Proxy Manager users can paste the `proxy_set_header` lines into a proxy host's **Advanced** tab.

## Check your setup

1. Open the guest hostname. **Add book** and other editing controls should be hidden.
2. Log in on the editor hostname as a user in `DND_TRACKER_ADMINS`. Editing controls should appear.
3. From another machine on your network, open `http://<app host>:8765` directly. The app should answer "Open this app through its public address (behind the login)."
4. Send a forged header to the guest hostname. Editing should still be refused:

   ```sh
   curl -s -H 'Remote-User: you@example.com' https://dnd.example.com/api/meta | grep -o '"can_edit":[a-z]*'
   ```

   This should print `"can_edit":false`.

## Troubleshooting

- **"Open this app through its public address" through the proxy.** The proxy connects from an address that isn't in `DND_TRACKER_TRUSTED_PROXIES`. Run `docker compose logs dnd-tracker` and look at the client address on the refused requests, then add it. If the proxy runs in Docker on the same host, it may connect from a Docker network address rather than the host's LAN address.
- **Logged in but read-only.** The top bar shows your name followed by "(view only)". The name or email the proxy sends doesn't match `DND_TRACKER_ADMINS`; the top bar shows the name the app received. If no name appears at all, the proxy isn't passing the identity headers. Check the spelling, or list both the username and the email.
- **Cover uploads fail with 413.** Raise the proxy's request body limit (`client_max_body_size` in nginx).
