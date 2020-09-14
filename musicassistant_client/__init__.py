"""
Music Assistant Client.

Simple wrapper for the websockets and rest Api's
provided by Music Assistant that allows for rapid development of apps
connected to Music Assistant.
"""

import asyncio
import functools
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, List, Union

import aiohttp

LOGGER = logging.getLogger("musicassistant-client")

EVENT_CONNECTED = "connected"
EVENT_PLAYER_ADDED = "player added"
EVENT_PLAYER_REMOVED = "player removed"
EVENT_PLAYER_CHANGED = "player changed"
EVENT_QUEUE_UPDATED = "queue updated"
EVENT_QUEUE_ITEMS_UPDATED = "queue items updated"
EVENT_SHUTDOWN = "application shutdown"
EVENT_PROVIDER_REGISTERED = "provider registered"
EVENT_PLAYER_CONTROL_REGISTERED = "player control registered"
EVENT_PLAYER_CONTROL_UPDATED = "player control updated"


class MusicAssistant:
    """Connection to MusicAssistant server (over websockets and rest api)."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        loop: asyncio.AbstractEventLoop = None,
    ) -> None:
        """
        Initialize the connection to MusicAssistant.

            :param url: full url to the MusicAssistant instance.
        """
        self._username = username
        self._password = password
        self._loop = loop
        self.__async_send_ws = None
        self._ws_callbacks: dict = {}
        self._players: dict = {}
        if url.startswith("https://"):
            self._use_ssl = True
            self._host = url.replace("https://", "")
        else:
            self._use_ssl = False
            self._host = url.replace("http://", "")
        self._http_session = None
        self._event_listeners: list = []
        self._ws_task = None
        self.__auth_token: dict = {}

    async def async_connect(self) -> None:
        """Connect to Music Assistant."""
        if not self._loop:
            self._loop = asyncio.get_running_loop()
        self._http_session = aiohttp.ClientSession(
            loop=self._loop, connector=aiohttp.TCPConnector()
        )
        await self.async_get_token()
        self._ws_task: asyncio.Task = self._loop.create_task(
            self.__async_mass_websocket()
        )

    async def async_close(self) -> None:
        """Close/stop the connection."""
        if self._ws_task:
            self._ws_task.cancel()
        if self._http_session:
            await self._http_session.close()
        LOGGER.info("Disconnected from Music Assistant")

    async def __aenter__(self):
        """Enter."""
        await self.async_connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Exit."""
        await self.async_close()

    def register_event_callback(
        self,
        cb_func: Callable[..., Union[None, Awaitable]],
        event_filter: Union[None, str, List[str]] = None,
    ) -> Callable:
        """
        Add callback for events.

        Returns function to remove the listener.
            :param cb_func: callback function or coroutine
            :param event_filter: Optionally only listen for these events
        """
        listener = (cb_func, event_filter)
        self._event_listeners.append(listener)

        def remove_listener() -> None:
            self._event_listeners.remove(listener)

        return remove_listener

    async def async_get_library_artists(self) -> List[dict]:
        """Return all library artists on Music Assistant."""
        return await self.__async_get_data("library/artists")

    async def async_get_library_albums(self) -> List[dict]:
        """Return all library albums on Music Assistant."""
        return await self.__async_get_data("library/albums")

    async def async_get_library_tracks(self) -> List[dict]:
        """Return all library tracks on Music Assistant."""
        return await self.__async_get_data("library/tracks")

    async def async_get_library_playlists(self) -> List[dict]:
        """Return all library playlists on Music Assistant."""
        return await self.__async_get_data("library/playlists")

    async def async_get_library_radios(self) -> List[dict]:
        """Return all library radios on Music Assistant."""
        return await self.__async_get_data("library/radios")

    async def async_get_artist(self, artist_id: str, provider_id: str) -> dict:
        """Return full artist object for specified artist/provider id.."""
        return await self.__async_get_data(
            f"artists/{artist_id}?provider={provider_id}"
        )

    async def async_get_album(self, album_id: str, provider_id: str) -> dict:
        """Return full album object for specified album/provider id.."""
        return await self.__async_get_data(f"artists/{album_id}?provider={provider_id}")

    async def async_get_track(self, track_id: str, provider_id: str) -> dict:
        """Return full track object for specified track/provider id.."""
        return await self.__async_get_data(f"artists/{track_id}?provider={provider_id}")

    async def async_get_playlist(self, playlist_id: str, provider_id: str) -> dict:
        """Return full playlist object for specified playlist/provider id.."""
        return await self.__async_get_data(
            f"artists/{playlist_id}?provider={provider_id}"
        )

    async def async_get_radio(self, radio_id: str, provider_id: str) -> dict:
        """Return full radio object for specified radio/provider id.."""
        return await self.__async_get_data(f"artists/{radio_id}?provider={provider_id}")

    async def async_get_image(
        self, media_type: str, item_id: str, provider_id: str, size: int = 500
    ) -> dict:
        """Return image (data) for the given media item."""
        return await self.__async_get_data(
            f"{media_type}/{item_id}?provider={provider_id}&size={size}"
        )

    async def async_get_image_url(
        self, media_type: str, item_id: str, provider_id: str, size: int = 500
    ) -> dict:
        """Return image url for the given media item."""
        scheme = "https" if self._use_ssl else "http"
        return f"{scheme}{self._host}/api/{media_type}/{item_id}?provider={provider_id}&size={size}"

    async def async_get_artist_toptracks(
        self, artist_id: str, provider_id: str
    ) -> List[dict]:
        """Return top tracks for specified artist/provider id."""
        return await self.__async_get_data(
            f"artists/{artist_id}/toptracks?provider={provider_id}"
        )

    async def async_get_artist_albums(
        self, artist_id: str, provider_id: str
    ) -> List[dict]:
        """Return albums for specified artist/provider id."""
        return await self.__async_get_data(
            f"artists/{artist_id}/albums?provider={provider_id}"
        )

    async def async_get_playlist_tracks(
        self, playlist_id: str, provider_id: str
    ) -> List[dict]:
        """Return the playlist's tracks for specified playlist/provider id."""
        return await self.__async_get_data(
            f"playlists/{playlist_id}/tracks?provider={provider_id}"
        )

    async def async_get_album_tracks(
        self, album_id: str, provider_id: str
    ) -> List[dict]:
        """Return the album's tracks for specified album/provider id."""
        return await self.__async_get_data(
            f"albums/{album_id}/tracks?provider={provider_id}"
        )

    async def async_search(
        self,
        query: str,
        media_types: str = "artists,albums,tracks,playlists,radios",
        limit=5,
    ) -> dict:
        """Return search results (media items) for given query."""
        return await self.__async_get_data(
            f"search/?query={query}&media_types={media_types}&limit={limit}"
        )

    async def async_get_players(self) -> List[dict]:
        """Return all players on Music Assistant."""
        return await self.__async_get_data("players")

    async def async_get_player(self, player_id: str) -> dict:
        """Return player details for the given player."""
        return await self.__async_get_data(f"players/{player_id}")

    async def async_player_command(
        self, player_id, cmd: str, cmd_args: Any = None
    ) -> bool:
        """Execute command on given player."""
        return await self.__async_post_data(f"players/{player_id}/cmd/{cmd}", cmd_args)

    async def async_get_player_queue(self, player_id: str) -> dict:
        """Return queue details for the given player."""
        return await self.__async_get_data(f"players/{player_id}/queue")

    async def async_get_player_queue_items(self, player_id: str) -> dict:
        """Return all queue items for the given player."""
        return await self.__async_get_data(f"players/{player_id}/queue/items")

    async def async_player_queue_command(
        self, player_id, cmd: str, cmd_args: Any = None
    ) -> bool:
        """Execute command on given player's queue."""
        return await self.__async_put_data(f"players/{player_id}/queue/{cmd}", cmd_args)

    async def async_play_media(
        self,
        player_id: str,
        media_items: Union[dict, List[dict]],
        queue_opt: str = "play",
    ):
        """
        Play media item(s) on the given player.

            :param player_id: player_id of the player to handle the command.
            :param media_item: media item(s) that should be played (single item or list of items)
            :param queue_opt:
                play -> Insert new items in queue and start playing at inserted position
                replace -> Replace queue contents with these items
                next -> Play item(s) after current playing item
                add -> Append new items at end of the queue
        """
        return await self.__async_post_data(
            f"players/{player_id}/play_media/{queue_opt}", media_items
        )

    async def async_get_token(self) -> str:
        """Get auth token by logging in."""
        # return existing token if we have one in memory
        if self.__auth_token and (self.__auth_token["expires"] > int(time.time()) + 20):
            return self.__auth_token["token"]
        tokeninfo = {}
        # retrieve token with login
        url = (
            f"https://{self._host}/login"
            if self._use_ssl
            else f"http://{self._host}/login"
        )
        headers = {"Content-Type": "application/json"}
        async with self._http_session.post(
            url,
            headers=headers,
            json={"username": self._username, "password": self._password},
            verify_ssl=False,
        ) as response:
            if response.status == 200:
                tokeninfo = await response.json()
        if tokeninfo:
            tokeninfo["expires"] = datetime.fromisoformat(
                tokeninfo["expires"]
            ).timestamp()
            self.__auth_token = tokeninfo
            LOGGER.debug("Succesfully logged in.")
            return self.__auth_token["token"]
        raise RuntimeError("Login failed. Invalid credentials provided?")

    async def send_event(self, message: str, message_details: Any = None) -> None:
        """Send event to Music Assistant."""
        if not self.__async_send_ws:
            raise RuntimeError("Not connected")
        await self.__async_send_ws(message, message_details)

    async def __async_mass_websocket(self) -> None:
        """Receive events from Music Assistant through websockets."""
        protocol = "wss" if self._use_ssl else "ws"
        while True:
            try:
                LOGGER.debug("Connecting to %s", self._host)
                token = await self.async_get_token()
                async with self._http_session.ws_connect(
                    f"{protocol}://{self._host}/ws", verify_ssl=False
                ) as conn:

                    # store handle to send messages to ws
                    async def send_msg(
                        message: str, message_details: Any = None
                    ) -> None:
                        """Handle to send messages back to WS."""
                        await conn.send_json(
                            {"message": message, "message_details": message_details}
                        )

                    self.__async_send_ws = send_msg
                    # send login message
                    await send_msg("login", token)
                    # keep listening for messages
                    async for msg in conn:

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            msg = data["message"]
                            msg_details = data["message_details"]
                            if msg == "login" and msg_details.get("exp"):
                                LOGGER.info("Connected to %s", self._host)
                                # subscribe to all events
                                await send_msg("add_event_listener")
                            else:
                                await self.__async_signal_event(msg, msg_details)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise Exception("error in websocket")

            except (
                aiohttp.client_exceptions.ClientConnectorError,
                ConnectionRefusedError,
            ) as exc:
                LOGGER.error(exc)
                self.__async_send_ws = None
                await asyncio.sleep(30)

    async def __async_get_data(self, endpoint: str) -> Union[List[dict], dict]:
        """Get data from hass rest api."""
        token = await self.async_get_token()
        url = f"http://{self._host}/api/{endpoint}"
        if self._use_ssl:
            url = f"https://{self._host}/api/{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % token,
        }
        async with self._http_session.get(
            url, headers=headers, verify_ssl=False
        ) as response:
            response = await response.json()
            if "items" in response:
                return response["items"]
            return response

    async def __async_post_data(self, endpoint: str, data: dict) -> Any:
        """Post data to hass rest api."""
        token = self.async_get_token()
        url = f"http://{self._host}/api/{endpoint}"
        if self._use_ssl:
            url = f"https://{self._host}/api/{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % token,
        }
        async with self._http_session.post(
            url, headers=headers, json=data, verify_ssl=False
        ) as response:
            return await response.json()

    async def __async_put_data(self, endpoint: str, data: dict) -> Any:
        """Put data to hass rest api."""
        token = await self.async_get_token()
        url = f"http://{self._host}/api/{endpoint}"
        if self._use_ssl:
            url = f"https://{self._host}/api/{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % token,
        }
        async with self._http_session.put(
            url, headers=headers, json=data, verify_ssl=False
        ) as response:
            return await response.json()

    async def __async_signal_event(self, event: str, event_details: Any = None) -> None:
        """Signal event to registered callbacks."""
        for cb_func, event_filter in self._event_listeners:
            if not (event_filter is None or event in event_filter):
                continue
            # call callback
            check_target = cb_func
            while isinstance(check_target, functools.partial):
                check_target = check_target.func
                check_target.args = (event, event_details)
            if asyncio.iscoroutine(check_target):
                self._loop.create_task(check_target)
            elif asyncio.iscoroutinefunction(check_target):
                self._loop.create_task(check_target(event, event_details))
            else:
                self._loop.run_in_executor(None, cb_func, event, event_details)
