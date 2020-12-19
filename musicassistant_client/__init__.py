"""
Music Assistant Client.

Simple wrapper for the websockets and rest Api's
provided by Music Assistant that allows for rapid development of apps
connected to Music Assistant.
"""

import asyncio
import functools
import logging
import uuid
from typing import Any, Awaitable, Callable, List, Optional, Union

import aiohttp

try:
    import ujson as json
except ImportError:
    import json

APP_ID = "musicassistant-client"
LOGGER = logging.getLogger(APP_ID)

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

# pylint: disable=c-extension-no-member


async def async_get_token(
    address: str, username: str, password: str, app_id: str = None
) -> dict:
    """
    Retrieve token to access a local MusicAssistant server.

        :param address: Websocket address to Music Assistant server
                       (e.g. ws://musicassistant.local:8095/ws).
        :param username: Username to authenticate.
        :param password: Password to authenticate.
        :param app_id: Some (friendly) identifier for your app.
                       A short-lived, single session token will be issued if appp_id is ommitted.
    """

    login_data = {"username": username, "password": password, "app_id": app_id}
    LOGGER.debug("Connecting to %s", address)
    async with aiohttp.ClientSession() as http_session:
        async with http_session.ws_connect(address) as websocket:
            # send login message
            await websocket.send_json({"command": "get_token", "data": login_data})
            # keep listening for messages
            async for msg in websocket:
                if msg.type != aiohttp.WSMsgType.text:
                    continue
                json_msg = msg.json(loads=json.loads)
                # incoming error message
                if "error" in json_msg:
                    # authentication error
                    LOGGER.error("Authentication failed: %s", json_msg["error"])
                    raise RuntimeError("Authentication failed: %s" % json_msg["error"])
                # return token info
                return json_msg["data"]


class MusicAssistant:
    """Connection to MusicAssistant server."""

    def __init__(
        self,
        address: str,
        token: str,
        loop: asyncio.AbstractEventLoop = None,
        client_session: aiohttp.ClientSession = None,
    ) -> None:
        """
        Initialize the connection to a MusicAssistant server.

            :param address: Websocket address to Music Assistant server
                       (e.g. ws://musicassistant.local:8095/ws).
            :param token: (long lived) JWT token to use for authentication, may be retrieved with get_token().
            :param port: The port to use for this Music Assistant instance, default is 8095.
            :param loop: Optionally provide the event loop.
            :param client_session: Optionally provide a aiohttp ClientSession.
        """
        if isinstance(token, dict):
            token = token["token"]
        self._address = address
        self._token = token
        self._loop = loop
        self._async_send_ws = None
        self._ws_results: dict = {}
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
        self._server_info = {}

    async def __aenter__(self):
        """Enter."""
        await self.async_connect()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Exit."""
        await self.async_close()

    @property
    def connected(self):
        """Return bool if the connection with the server is alive."""
        return self._connected

    @property
    def server_info(self):
        """Return server info."""
        return self._server_info

    @property
    def address(self):
        """Return server address."""
        return self._server_info.get("address", self._address)

    @property
    def server_id(self):
        """Return server id."""
        return self._server_info.get("id")

    @property
    def server_version(self):
        """Return server version."""
        return self._server_info.get("version")

    @property
    def server_name(self):
        """Return server name."""
        return self._server_info.get("friendly_name")

    async def async_connect(self) -> None:
        """Connect to a local Music Assistant server."""
        if not self._loop:
            self._loop = asyncio.get_event_loop()
        if not self._http_session_provided:
            self._http_session = aiohttp.ClientSession(
                loop=self._loop, connector=aiohttp.TCPConnector()
            )
        self._ws_task = self._loop.create_task(self.__async_mass_websocket_connect())

    async def async_close(self) -> None:
        """Close/stop the connection."""
        if self._ws_task:
            self._ws_task.cancel()
        if self._http_session and not self._http_session_provided:
            await self._http_session.close()

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
        await self.async_send_command(
            f"players/controls/{control_id}/register", {"control": control}
        )

    async def async_update_player_control(self, control_id: str, new_state: Any):
        """
        Process updated state of an existing playercontrol.

            :param control_id: A unique id for this PlayerControl.
            :param new_state: The current/new state for this control.
        """
        if control_id not in self._player_controls:
            raise RuntimeError("Invalid player control")
        control = self._player_controls[control_id][0]
        control["state"] = new_state
        await self.async_send_command(
            f"players/controls/{control_id}/update", {"control": control}
        )

    async def async_get_server_info(self) -> dict:
        """Return the (discovery) server details for this Music Assistant server."""
        return await self.async_get_data("info")

    async def async_get_library_artists(self) -> List[dict]:
        """Return all library artists on Music Assistant."""
        return await self.async_get_data("library/artists")

    async def async_get_library_albums(self) -> List[dict]:
        """Return all library albums on Music Assistant."""
        return await self.async_get_data("library/albums")

    async def async_get_library_tracks(self) -> List[dict]:
        """Return all library tracks on Music Assistant."""
        return await self.async_get_data("library/tracks")

    async def async_get_library_playlists(self) -> List[dict]:
        """Return all library playlists on Music Assistant."""
        return await self.async_get_data("library/playlists")

    async def async_get_library_radios(self) -> List[dict]:
        """Return all library radios on Music Assistant."""
        return await self.async_get_data("library/radios")

    async def async_get_item(self, item_id: str, provider_id: str, media_type: str):
        """Get single music item by id and media type."""
        return await self.async_get_data(f"items/{media_type}/{provider_id}/{item_id}")

    async def async_get_artist(self, artist_id: str, provider_id: str) -> dict:
        """Return full artist object for specified artist/provider id.."""
        return await self.async_get_data(f"artists/{provider_id}/{artist_id}")

    async def async_get_album(self, album_id: str, provider_id: str) -> dict:
        """Return full album object for specified album/provider id.."""
        return await self.async_get_data(f"albums/{provider_id}/{album_id}")

    async def async_get_track(self, track_id: str, provider_id: str) -> dict:
        """Return full track object for specified track/provider id.."""
        return await self.async_get_data(f"tracks/{provider_id}/{track_id}")

    async def async_get_playlist(self, playlist_id: str, provider_id: str) -> dict:
        """Return full playlist object for specified playlist/provider id.."""
        return await self.async_get_data(f"playlists/{provider_id}/{playlist_id}")

    async def async_get_radio(self, radio_id: str, provider_id: str) -> dict:
        """Return full radio object for specified radio/provider id.."""
        return await self.async_get_data(f"radios/{provider_id}/{radio_id}")

    async def async_get_image_thumb(
        self,
        media_item: Optional[dict] = None,
        url: Optional[str] = None,
        size: int = 500,
    ) -> str:
        """Return base64 thumbnail image (data) for the given media item OR url."""
        return await self.async_get_data(
            "images/thumb", {"url": url, "item": media_item, "size": size}
        )

    async def async_get_media_item_image_url(self, media_item: dict):
        """Get full/original image url for given media_item by providing the media item."""
        if not media_item:
            return None
        if media_item.get("metadata") and media_item["metadata"].get("image"):
            return media_item["metadata"]["image"]
        if media_item.get("album") and media_item["album"].get("metadata"):
            if media_item["album"]["metadata"].get("image"):
                return media_item["album"]["metadata"]["image"]
        if media_item.get("artist") and media_item["artist"].get("metadata"):
            if media_item["artist"]["metadata"].get("image"):
                return media_item["artist"]["metadata"]["image"]
        # get full item
        media_item = await self.async_get_item(
            media_item["item_id"], media_item["provider"], media_item["media_type"]
        )
        if media_item.get("metadata") and media_item["metadata"].get("image"):
            return media_item["metadata"]["image"]
        if media_item.get("album") and media_item["album"].get("metadata"):
            if media_item["album"]["metadata"].get("image"):
                return media_item["album"]["metadata"]["image"]
        return None

    async def async_get_artist_toptracks(
        self, artist_id: str, provider_id: str
    ) -> List[dict]:
        """Return top tracks for specified artist/provider id."""
        return await self.async_get_data(f"artists/{provider_id}/{artist_id}/tracks")

    async def async_get_artist_albums(
        self, artist_id: str, provider_id: str
    ) -> List[dict]:
        """Return albums for specified artist/provider id."""
        return await self.async_get_data(f"artists/{provider_id}/{artist_id}/albums")

    async def async_get_playlist_tracks(
        self, playlist_id: str, provider_id: str
    ) -> List[dict]:
        """Return the playlist's tracks for specified playlist/provider id."""
        return await self.async_get_data(
            f"playlists/{provider_id}/{playlist_id}/tracks"
        )

    async def async_get_album_tracks(
        self, album_id: str, provider_id: str
    ) -> List[dict]:
        """Return the album's tracks for specified album/provider id."""
        return await self.async_get_data(f"albums/{provider_id}/{album_id}/tracks")

    async def async_search(
        self, search_query: str, media_types: List[str] = None, limit=10
    ) -> dict:
        """
        Perform global search for media items on all providers.

            :param search_query: Search query.
            :param media_types: A list of media_types to include.
            :param limit: number of items to return in the search (per type). All if ommitted.
        """
        if media_types is None:
            media_types = ["artists", "albums", "tracks", "playlists", "radios"]
        data = {
            "search_query": search_query,
            "media_types": media_types,
            "limit": limit,
        }
        return await self.async_get_data("search", data)

    async def async_get_players(self) -> List[dict]:
        """Return all players on Music Assistant."""
        return await self.async_get_data("players")

    async def async_get_player(self, player_id: str) -> dict:
        """Return player details for the given player."""
        return await self.async_get_data(f"players/{player_id}")

    async def async_player_command(
        self, player_id, cmd: str, cmd_args: Any = None
    ) -> bool:
        """Execute command on given player."""
        if cmd_args is not None:
            return await self.async_send_command(
                f"players/{player_id}/cmd/{cmd}/{cmd_args}"
            )
        return await self.async_send_command(f"players/{player_id}/cmd/{cmd}")

    async def async_get_player_queue(self, queue_id: str) -> dict:
        """Return queue details for the given playerqueue."""
        return await self.async_get_data(f"players/{queue_id}/queue")

    async def async_get_player_queue_items(self, queue_id: str) -> dict:
        """Return all queue items for the given player."""
        return await self.async_get_data(f"players/{queue_id}/queue/items")

    async def async_player_queue_cmd_set_shuffle(
        self, queue_id: str, enable_shuffle: bool = False
    ):
        """Send enable/disable shuffle command to given playerqueue."""
        return await self.async_send_command(
            f"players/{queue_id}/queue/cmd/shuffle_enabled/{enable_shuffle}"
        )

    async def async_player_queue_cmd_set_repeat(
        self, queue_id: str, enable_repeat: bool = False
    ):
        """Send enable/disable repeat command to given playerqueue."""
        return await self.async_send_command(
            f"players/{queue_id}/queue/cmd/repeat_enabled/{enable_repeat}"
        )

    async def async_player_queue_cmd_clear(self, queue_id: str):
        """Clear all items in the player's queue."""
        return await self.async_send_command(f"players/{queue_id}/queue/cmd/clear")

    async def async_player_queue_cmd_next(self, queue_id: str):
        """Send next track command to player's queue."""
        return await self.async_send_command(f"players/{queue_id}/queue/cmd/next")

    async def async_player_queue_cmd_previous(self, queue_id: str):
        """Send previous track command to player's queue."""
        return await self.async_send_command(f"players/{queue_id}/queue/cmd/previous")

    async def async_player_queue_cmd_move_item(
        self, queue_id: str, queue_item_id: str, pos_shift: int = 1
    ):
        """
        Move queue item x up/down the queue.

        param pos_shift: move item x positions down if positive value
                         move item x positions up if negative value
                         move item to top of queue as next item if 0
        """
        return await self.async_send_command(
            f"players/{queue_id}/queue/cmd/move{queue_item_id}/{pos_shift}"
        )

    async def async_play_index(self, queue_id: str, index: Union[int, str]) -> None:
        """Play item at index (or item_id) X in queue."""
        return await self.async_send_command(
            f"players/{queue_id}/queue/cmd/index/{index}"
        )

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
        return await self.async_send_command(
            f"players/{player_id}/play_media",
            {"items": media_items, "queue_opt": queue_opt},
        )

    async def async_cmd_play_uri(self, player_id: str, uri: str):
        """
        Play the specified uri/url on the given player.

        Will create a fake track on the queue.

            :param player_id: player_id of the player to handle the command.
            :param uri: Url/Uri that can be played by a player.
        """
        return await self.async_send_command(
            f"players/{player_id}/play_uri",
            {"uri": uri},
        )

    async def async_send_event(self, event: str, data: Any = None) -> None:
        """Send event to Music Assistant."""
        if not self.connected:
            # wait max 5 seconds for server connected
            count = 0
            while not self.connected and count < 5:
                await asyncio.sleep(1)
                count += 1
            if not self.connected:
                LOGGER.debug("Ignoring command, server is not connected")
                return
        await self._async_send_ws(event=event, data=data)

    async def async_send_command(
        self, command: str, data: Any = None, msg_id: Any = None
    ) -> None:
        """Send command to Music Assistant."""
        if not self.connected:
            # wait max 5 seconds for server connected
            count = 0
            while not self.connected and count < 5:
                await asyncio.sleep(1)
                count += 1
            if not self.connected:
                LOGGER.debug("Ignoring command, server is not connected")
                return
        await self._async_send_ws(command=command, data=data, id=msg_id)

    async def async_get_data(
        self, endpoint: str, data: Any = None
    ) -> Union[List[dict], dict]:
        """Send command to server and wait for result."""
        msg_id = str(uuid.uuid4())
        self._ws_results[msg_id] = asyncio.Queue(1)
        await self.async_send_command(endpoint, data=data, msg_id=msg_id)
        # wait for result which will be put in the queue
        result = await self._ws_results[msg_id].get()
        self._ws_results[msg_id].task_done()
        del self._ws_results[msg_id]
        return result

    async def __async_mass_websocket_connect(self) -> None:
        """Handle websocket connection and reconnects."""
        while True:
            try:
                await self.__async_mass_websocket()
            except (
                aiohttp.client_exceptions.ClientConnectorError,
                aiohttp.client_exceptions.ClientConnectionError,
                aiohttp.client_exceptions.ServerConnectionError,
                aiohttp.client_exceptions.ServerDisconnectedError,
                ConnectionRefusedError,
            ):
                self._async_send_ws = None
                self._connected = False
                LOGGER.debug(
                    "Websocket disconnected, will auto reconnect in 30 seconds."
                )
                await asyncio.sleep(30)

    async def __async_mass_websocket(self) -> None:
        """Handle websocket connection to/from Music Assistant."""

        LOGGER.debug("Connecting to %s", self._address)
        async with self._http_session.ws_connect(self._address) as websocket:

            # store handle to send messages to ws
            async def send_msg(*args, **kwargs) -> None:
                """Handle to send messages back to WS."""
                try:
                    await websocket.send_json(kwargs, dumps=json.dumps)
                except Exception:  # pylint: disable=broad-except
                    LOGGER.debug("error while sending message to ws", exc_info=True)

            self._async_send_ws = send_msg
            # send login message
            await send_msg(command="auth", data=self._token)
            # keep listening for messages
            async for msg in websocket:
                if msg.type == aiohttp.WSMsgType.error:
                    LOGGER.warning(
                        "ws connection closed with exception %s", websocket.exception()
                    )
                if msg.type != aiohttp.WSMsgType.text:
                    continue
                # regular message
                if msg.data == "close":
                    await websocket.close()
                    break
                json_msg = msg.json(loads=json.loads)
                # incoming error message
                if "error" in json_msg:
                    # authentication error
                    if json_msg.get("result") == "auth":
                        LOGGER.error("Authentication failed: %s", json_msg["error"])
                        raise RuntimeError(
                            "Authentication failed: %s" % json_msg["error"]
                        )
                    # log all other errors
                    LOGGER.error(json_msg)
                    continue
                # incoming event message
                if "event" in json_msg:
                    event = json_msg["event"]
                    event_data = json_msg.get("data")
                    # player control state request
                    if "players/controls/" in event and "/state" in event:
                        control_id = event.split("/")[2]
                        control = self._player_controls.get(control_id)
                        if control:
                            await control[1](event_data)
                    else:
                        # handle regular event
                        await self.__async_signal_event(event, event_data)
                # incoming command from server to client
                if "command" in json_msg:
                    # simply broadcast the command as event
                    await self.__async_signal_event(
                        json_msg["command"], json_msg.get("data")
                    )
                # handle result of requested command
                if "result" in json_msg:
                    if json_msg["result"] == "auth":
                        # authentication succeeded
                        self._connected = True
                        LOGGER.info("Connected to %s", self._address)
                        await self.__async_signal_event(EVENT_CONNECTED)
                        asyncio.create_task(self.__async_get_server_info())
                    if "id" in json_msg and json_msg["id"] in self._ws_results:
                        await self._ws_results[json_msg["id"]].put(json_msg.get("data"))

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

    async def __async_get_server_info(self):
        """Get server info."""
        self._server_info = await self.async_get_data("info")
