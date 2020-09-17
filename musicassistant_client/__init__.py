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
EVENT_QUEUE_TIME_UPDATED = "queue time updated"
EVENT_SHUTDOWN = "application shutdown"
EVENT_PROVIDER_REGISTERED = "provider registered"
EVENT_PLAYER_CONTROL_REGISTERED = "player control registered"
EVENT_PLAYER_CONTROL_UNREGISTERED = "player control unregistered"
EVENT_PLAYER_CONTROL_UPDATED = "player control updated"
EVENT_SET_PLAYER_CONTROL_STATE = "set player control state"
EVENT_REGISTER_PLAYER_CONTROL = "register player control"
EVENT_UNREGISTER_PLAYER_CONTROL = "unregister player control"
EVENT_UPDATE_PLAYER_CONTROL = "update player control"


class MusicAssistant:
    """Connection to MusicAssistant server (over websockets and rest api)."""

    def __init__(
        self,
        host: str,
        port: int = 8095,
        username: str = "admin",
        password: str = "",
        use_ssl: bool = False,
        loop: asyncio.AbstractEventLoop = None,
        client_session: aiohttp.ClientSession = None,
    ) -> None:
        """
        Initialize the connection to MusicAssistant.

            :param host: Hostname/url to the MusicAssistant instance.
            :param port: The port to use for this Music Assistant instance.
            :param username: The username, defaults to admin.
            :param password: The password, defaults to empty.
            :param use_ssl: Use SSL for the connection.
            :param loop: Optionally provide the evnt loop.
            :param client_session: Optionally provide a aiohttp ClientSession.
        """
        if host.endswith("/"):
            host = host[:-1]  # strip trailing slash
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_ssl = use_ssl
        self._loop = loop
        self._async_send_ws = None
        self._ws_callbacks: dict = {}
        self._players: dict = {}
        if client_session:
            self._http_session_provided = True
            self._http_session = client_session
        else:
            self._http_session_provided = False
            self._http_session = None
        self._event_listeners: list = []
        self._ws_task = None
        self._auth_token: dict = {}
        self._connected = False
        self._player_controls = {}

    @property
    def host(self):
        """Return the host of the connected Music Assistant Server."""
        return self._host

    @property
    def port(self):
        """Return the port of the connected Music Assistant Server."""
        return self._port

    @property
    def base_url(self):
        """Return the base url of the connected Music Assistant Server."""
        if self._use_ssl:
            return f"https://{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def connected(self):
        """Return bool if the connection with the server is alive."""
        return self._connected

    async def async_connect(self, auto_retry: bool = False) -> None:
        """
        Connect to Music Assistant.

        :param auto_retry: Auto retry if the server is not (yet) available.

        """
        if not self._loop:
            self._loop = asyncio.get_running_loop()
        if not self._http_session_provided:
            self._http_session = aiohttp.ClientSession(
                loop=self._loop, connector=aiohttp.TCPConnector()
            )
        try:
            await self.async_get_token()
            self._ws_task: asyncio.Task = self._loop.create_task(
                self.__async_mass_websocket()
            )
            self._connected = True
        except (
            aiohttp.client_exceptions.ClientConnectorError,
            ConnectionRefusedError,
        ) as exc:
            if auto_retry:
                # schedule the reconnect
                LOGGER.debug(
                    "Connection to the server not available, will rety in 60 seconds..."
                )
                self._loop.call_later(
                    60, self._loop.create_task, self.async_connect(auto_retry)
                )
            else:
                raise ConnectionFailedError from exc

    async def async_close(self) -> None:
        """Close/stop the connection."""
        if self._ws_task:
            self._ws_task.cancel()
        if self._http_session and not self._http_session_provided:
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

    async def async_register_player_control(
        self,
        control_type: int,
        control_id: str,
        provider_name: str,
        name: str,
        state: Any,
        cb_func: Callable[..., Union[None, Awaitable]],
    ):
        """
        Register a playercontrol with Music Assistant.

            :param control_type: Type of the PlayerControl. 0 for PowerControl, 1 for VolumeControl
            :param control_id: A unique id for this PlayerControl.
            :param provider_name: Your application name.
            :param name: A friendly name for this control.
            :param state: The current state for this control.
            :param cb_func: A callback that will be called when a new state needs to be set.
        """
        control = {
            "type": control_type,
            "control_id": control_id,
            "provider": provider_name,
            "name": name,
            "state": state,
        }
        self._player_controls[control_id] = (control, cb_func)
        await self.async_send_event(EVENT_REGISTER_PLAYER_CONTROL, control)

    async def async_update_player_control(self, control_id: str, new_state: Any):
        """
        Update state of an existing playercontrol.

            :param control_id: A unique id for this PlayerControl.
            :param new_state: The current/new state for this control.
        """
        if control_id not in self._player_controls:
            raise RuntimeError("Invalid player control")
        control = self._player_controls[control_id][0]
        control["state"] = new_state
        await self.async_send_event(EVENT_PLAYER_CONTROL_UPDATED, control)

    async def async_get_server_info(self) -> dict:
        """Return the (discovery) server details for this Music Assistant server."""
        result = await self.__async_get_data("info")
        return result

    async def async_get_library_artists(self) -> List[dict]:
        """Return all library artists on Music Assistant."""
        result = await self.__async_get_data("library/artists")
        return result["items"]

    async def async_get_library_albums(self) -> List[dict]:
        """Return all library albums on Music Assistant."""
        result = await self.__async_get_data("library/albums")
        return result["items"]

    async def async_get_library_tracks(self) -> List[dict]:
        """Return all library tracks on Music Assistant."""
        result = await self.__async_get_data("library/tracks")
        return result["items"]

    async def async_get_library_playlists(self) -> List[dict]:
        """Return all library playlists on Music Assistant."""
        result = await self.__async_get_data("library/playlists")
        return result["items"]

    async def async_get_library_radios(self) -> List[dict]:
        """Return all library radios on Music Assistant."""
        result = await self.__async_get_data("library/radios")
        return result["items"]

    async def async_get_artist(self, artist_id: str, provider_id: str) -> dict:
        """Return full artist object for specified artist/provider id.."""
        return await self.__async_get_data(
            f"artists/{artist_id}?provider={provider_id}"
        )

    async def async_get_album(self, album_id: str, provider_id: str) -> dict:
        """Return full album object for specified album/provider id.."""
        return await self.__async_get_data(f"albums/{album_id}?provider={provider_id}")

    async def async_get_track(self, track_id: str, provider_id: str) -> dict:
        """Return full track object for specified track/provider id.."""
        return await self.__async_get_data(f"tracks/{track_id}?provider={provider_id}")

    async def async_get_playlist(self, playlist_id: str, provider_id: str) -> dict:
        """Return full playlist object for specified playlist/provider id.."""
        return await self.__async_get_data(
            f"playlists/{playlist_id}?provider={provider_id}"
        )

    async def async_get_radio(self, radio_id: str, provider_id: str) -> dict:
        """Return full radio object for specified radio/provider id.."""
        return await self.__async_get_data(f"radios/{radio_id}?provider={provider_id}")

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

    async def async_get_media_item_image_url(self, media_item: dict, size=150):
        """Get image url for given media_item by providing the media item."""
        if not media_item:
            return None
        if media_item["metadata"].get("image"):
            return media_item["metadata"]["image"]
        if media_item.get("album", {}).get("metdata", {}).get("image"):
            return media_item["metadata"]["album"]["image"]
        if media_item["provider"] == "database":
            item_type = media_item["media_type"]
            item_id = media_item["item_id"]
            item_prov = media_item["provider"]
            base_url = f"{self.base_url}/api"
            return f"{base_url}/{item_type}/{item_id}/thumb?provider={item_prov}&size={size}"
        return None

    async def async_get_artist_toptracks(
        self, artist_id: str, provider_id: str
    ) -> List[dict]:
        """Return top tracks for specified artist/provider id."""
        result = await self.__async_get_data(
            f"artists/{artist_id}/toptracks?provider={provider_id}"
        )
        return result["items"]

    async def async_get_artist_albums(
        self, artist_id: str, provider_id: str
    ) -> List[dict]:
        """Return albums for specified artist/provider id."""
        result = await self.__async_get_data(
            f"artists/{artist_id}/albums?provider={provider_id}"
        )
        return result["items"]

    async def async_get_playlist_tracks(
        self, playlist_id: str, provider_id: str
    ) -> List[dict]:
        """Return the playlist's tracks for specified playlist/provider id."""
        result = await self.__async_get_data(
            f"playlists/{playlist_id}/tracks?provider={provider_id}"
        )
        return result["items"]

    async def async_get_album_tracks(
        self, album_id: str, provider_id: str
    ) -> List[dict]:
        """Return the album's tracks for specified album/provider id."""
        result = await self.__async_get_data(
            f"albums/{album_id}/tracks?provider={provider_id}"
        )
        return result["items"]

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
        if self._auth_token and (self._auth_token["expires"] > int(time.time()) + 20):
            return self._auth_token["token"]
        tokeninfo = {}
        # retrieve token with login
        url = f"{self.base_url}/api/login"
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
            self._auth_token = tokeninfo
            LOGGER.debug("Succesfully logged in.")
            return self._auth_token["token"]
        raise InvalidCredentialsError("Login failed. Invalid credentials provided?")

    async def async_send_event(self, message: str, message_details: Any = None) -> None:
        """Send event/command to Music Assistant."""
        if not self._async_send_ws:
            raise NotConnectedError("Not connected")
        await self._async_send_ws(message, message_details)

    async def __async_mass_websocket(self) -> None:
        """Receive events from Music Assistant through websockets."""
        protocol = "wss" if self._use_ssl else "ws"
        while True:
            try:
                LOGGER.debug("Connecting to %s", self._host)
                token = await self.async_get_token()
                async with self._http_session.ws_connect(
                    f"{protocol}://{self._host}:{self._port}/ws", verify_ssl=False
                ) as conn:

                    # store handle to send messages to ws
                    async def send_msg(
                        message: str, message_details: Any = None
                    ) -> None:
                        """Handle to send messages back to WS."""
                        await conn.send_json(
                            {"message": message, "message_details": message_details}
                        )

                    self._async_send_ws = send_msg
                    # send login message
                    await send_msg("login", token)
                    # keep listening for messages
                    async for msg in conn:

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = msg.json()
                            msg = data["message"]
                            msg_details = data["message_details"]
                            if msg == "login" and msg_details.get("exp"):
                                LOGGER.debug("Connected to %s", self._host)
                                await self.__async_signal_event(EVENT_CONNECTED)
                                # subscribe to all events
                                await send_msg("add_event_listener")
                            if msg == EVENT_SET_PLAYER_CONTROL_STATE:
                                control = self._player_controls.get(
                                    msg_details["control_id"]
                                )
                                if not control:
                                    continue
                                await control[1](msg_details["state"])
                            else:
                                await self.__async_signal_event(msg, msg_details)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise Exception("error in websocket")

            except (
                aiohttp.client_exceptions.ClientConnectorError,
                aiohttp.client_exceptions.ClientConnectionError,
                aiohttp.client_exceptions.ServerConnectionError,
                aiohttp.client_exceptions.ServerDisconnectedError,
                ConnectionRefusedError,
            ) as exc:
                LOGGER.debug(
                    "Websocket disconnected, will auto reconnect in 30 seconds. %s", exc
                )
                self._async_send_ws = None
                await asyncio.sleep(30)

    async def __async_get_data(self, endpoint: str) -> Union[List[dict], dict]:
        """Get data from hass rest api."""
        if not self._connected:
            raise NotConnectedError("Not connected")
        token = await self.async_get_token()
        url = f"{self.base_url}/api/{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % token,
        }
        async with self._http_session.get(
            url, headers=headers, verify_ssl=False
        ) as response:
            return await response.json()

    async def __async_post_data(self, endpoint: str, data: Any) -> Any:
        """Post data to hass rest api."""
        if not self._connected:
            raise NotConnectedError("Not connected")
        token = await self.async_get_token()
        url = f"{self.base_url}/api/{endpoint}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % token,
        }
        async with self._http_session.post(
            url, headers=headers, json=data, verify_ssl=False
        ) as response:
            return await response.json()

    async def __async_put_data(self, endpoint: str, data: Any) -> Any:
        """Put data to hass rest api."""
        if not self._connected:
            raise NotConnectedError("Not connected.")
        token = await self.async_get_token()
        url = f"{self.base_url}/api/{endpoint}"
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


class InvalidCredentialsError(Exception):
    """Exception raised when invalid credentials supplied."""


class NotConnectedError(Exception):
    """Exception raised when trying to call a method when the connection was not initialized."""


class ConnectionFailedError(Exception):
    """Exception raised when the connection could not be established."""
