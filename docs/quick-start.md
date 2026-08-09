# Quick Start

This guide gets a new Jellyfin Media Assistant installation from HACS to a first Assist request.

## 1. Prerequisites

You need:

- Home Assistant 2026.7.0 or newer;
- a Jellyfin server reachable from Home Assistant;
- a Jellyfin API key;
- the Jellyfin user ID whose visible libraries should be searchable; and
- for supported beta playback, a Chromecast exposed in Home Assistant as a `media_player` entity.

You do NOT need:

- Home Assistant Jellyfin integration
- JellyHA integration

Jellyfin Media Assistant connects directly to your Jellyfin server using the server URL, API key, and user ID you provide during setup.

## 2. Find your Jellyfin connection information

Before setting up Jellyfin Media Assistant, gather the following information from your Jellyfin server.

### Server URL

Use the address that Home Assistant can use to reach your Jellyfin server.

For example:

```text
http://jellyfin.local:8096
```

or, if you use HTTPS:

```text
https://jellyfin.example.com
```

The address must be reachable from the Home Assistant server itself, not just from the device you are using to configure Home Assistant.

### API key

In Jellyfin:

1. Sign in with an administrator account.
2. Open the **Dashboard**.
3. Open **API Keys**.
4. Create a new API key.
5. Give it a recognizable name such as `Jellyfin Media Assistant`.
6. Copy the generated key.

Treat the API key like a password. Do not publish it in screenshots, logs, GitHub issues, or configuration examples.

### Jellyfin user ID

Jellyfin Media Assistant searches the libraries available to a specific Jellyfin user. Choose the user whose library access you want the integration to use.

1. In the Jellyfin Dashboard, open **Users**.
2. Select the user you want Jellyfin Media Assistant to use.
3. Look at the browser address bar for a value similar to:

```text
userId=<JELLYFIN_USER_ID>
```

4. Copy only the value after `userId=`.

The user ID is different from the user's display name.

The selected user's Jellyfin library permissions determine which media Jellyfin Media Assistant can find when searching.


## 3. Install the integration

### HACS custom repository

Until the integration is part of HACS' default repository list:

1. Open HACS.
2. Open **Custom repositories**.
3. Add `https://github.com/sugarlover/jellyfin-media-assistant` as an **Integration** repository.
4. Install **Jellyfin Media Assistant**.
5. Restart Home Assistant.

### Manual installation

Copy the repository directory `custom_components/jellyfin_assist` to:

```text
<home-assistant-config>/custom_components/jellyfin_assist
```

Then restart Home Assistant.

## 4. Connect Jellyfin

Go to **Settings → Devices & services → Add integration → Jellyfin Media Assistant**.

Enter:

- **Jellyfin server URL** — the complete `http://` or `https://` URL Home Assistant uses to reach Jellyfin;
- **API key** — preferably a dedicated Jellyfin API key for this integration;
- **Jellyfin user ID** — the user whose accessible libraries define the searchable catalog; and
- **Verify SSL certificate** — normally enabled; disable only when a trusted local setup requires it.

The setup flow validates the connection before creating the config entry.

## 5. Configure playback targets

Open **Settings → Devices & services → Jellyfin Media Assistant → Configure**.

You can set:

- **Default Media Player** — used when a request does not name a player.
- **Playback Targets** — an optional allowlist of additional `media_player` entities Jellyfin Media Assistant may resolve and use.

For the first beta, use Chromecast targets for supported playback.

If you want Assist to recognize extra room/device wording, add aliases to the Home Assistant media-player entity. Jellyfin Media Assistant reads native Home Assistant names and aliases instead of shipping household-specific aliases.

## 6. Use Assist

The integration automatically provisions its English custom sentence file. A normal installation does not require manually copying anything into `custom_sentences`.

Try a request such as:

> Play the movie The Martian on the living room TV.

Or, if you configured a default player:

> Play the movie The Martian.

If several catalog items are plausible, Assist presents numbered choices. Reply with a selection such as:

> Number 2.

See [Voice & Assist Command Guide](voice-commands.md) for more tested command forms.

## 7. Confirm the queue

Try:

> What's playing on the living room TV?

and:

> Queue status on the living room TV.

Albums, artists, and TV seasons may create multi-item queues. Queue state is persisted through Home Assistant storage and survives a Home Assistant restart.

## Troubleshooting first setup

Download diagnostics from **Settings → Devices & services → Jellyfin Media Assistant** and check:

- Jellyfin connection/catalog status;
- configured playback targets;
- queue storage state;
- registered native voice intents; and
- managed voice-sentence status.

The API key is redacted from diagnostics.

For more detail, see [Configuration](configuration.md), [Known Limitations](known-limitations.md), and the troubleshooting section in the root [README](../README.md).
